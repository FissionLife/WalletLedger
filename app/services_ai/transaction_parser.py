# Role 5: Transaction engine (chat / PDF / SMS parsing) and financial insights.
# Everything here is deterministic (regex + keyword rules) so it works with no LLM key.
import asyncio
import io
import re
from datetime import datetime
from typing import Any

from app.db import SessionLocal
from app.services import ledger

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Food & Dining": (
        "swiggy",
        "zomato",
        "dinner",
        "lunch",
        "breakfast",
        "coffee",
        "pizza",
        "burger",
        "restaurant",
        "cafe",
        "starbucks",
        "dominos",
        "mcdonald",
        "kfc",
        "snack",
        "food",
        "biryani",
    ),
    "Groceries": ("grocery", "groceries", "bigbasket", "blinkit", "zepto", "dmart", "instamart"),
    "Transport": (
        "uber",
        "ola",
        "rapido",
        "fuel",
        "petrol",
        "diesel",
        "cab",
        "metro",
        "bus",
        "auto",
        "taxi",
        "irctc",
        "train",
        "flight",
        "parking",
        "toll",
    ),
    "Shopping": ("amazon", "flipkart", "myntra", "ajio", "clothes", "shoes", "shopping", "meesho"),
    "Entertainment": (
        "netflix",
        "spotify",
        "hotstar",
        "prime video",
        "youtube",
        "movie",
        "bookmyshow",
        "game",
    ),
    "Bills & Utilities": (
        "rent",
        "electricity",
        "water bill",
        "gas bill",
        "recharge",
        "wifi",
        "broadband",
        "internet",
        "airtel",
        "jio",
        "vodafone",
        "bill",
        "insurance",
        "emi",
    ),
    "Health": ("pharmacy", "medicine", "doctor", "hospital", "gym", "apollo", "medplus", "clinic"),
    "Education": ("course", "udemy", "tuition", "school", "college", "books"),
    "Investments": ("mutual fund", "sip", "zerodha", "groww", "stocks", "investment"),
    "Salary": ("salary", "payroll", "stipend"),
}
ESSENTIAL = {"Bills & Utilities", "Education", "Salary"}
DISCRETIONARY = {"Food & Dining", "Shopping", "Entertainment", "Transport"}

_AMOUNT = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k\b|l\b|lakh)?"
_AMOUNT_RE = re.compile(_AMOUNT, re.I)
_STOP = r"(?=\s+(?:for|via|using|from|with|through|on|in|into|at|to|by|today|yesterday)\b|[.,!?]|$)"
_KEY_RE = re.compile(r"\b(AIza[\w-]{20,}|sk-ant-[\w-]{16,}|sk-[\w-]{16,}|gsk_[\w]{16,})")


def categorize(*texts: str | None) -> str | None:
    blob = " ".join(t.lower() for t in texts if t)
    for category, words in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", blob) for w in words):
            return category
    return None


def _to_amount(num: str, suffix: str | None) -> float:
    value = float(num.replace(",", ""))
    s = (suffix or "").lower()
    if s == "k":
        value *= 1_000
    elif s in ("l", "lakh"):
        value *= 100_000
    return value


def _first_amount(text: str) -> float | None:
    for m in _AMOUNT_RE.finditer(text):
        # ignore digits glued to letters (e.g. order ids "A1234") or part of an API key
        start = m.start(1)
        if start > 0 and text[start - 1].isalpha():
            continue
        try:
            return _to_amount(m.group(1), m.group(2))
        except ValueError:
            continue
    return None


def _grab(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip(" .,'\"") if m else None


def _clean_account(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"^(?:my|the)\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"\s+(?:account|acc)$", "", name, flags=re.I)
    return name.title() if name else None


def parse_chat_expense(text: str) -> dict[str, Any]:
    """Rule-based intent + entity extraction for a chat message.

    Returns {"intent": ..., plus amount/account/to_account/category/merchant/description/api_key}.
    Intents: expense, income, transfer, balance, report, advice, set_key, other.
    """
    text = (text or "").strip()
    low = text.lower()
    result: dict[str, Any] = {"intent": "other"}

    key_match = _KEY_RE.search(text)
    if key_match and re.search(r"\bkey\b|token", low):
        return {"intent": "set_key", "api_key": key_match.group(1)}

    amount = _first_amount(text)

    if re.search(r"\b(transfer(?:red)?|moved?|shifted?|sent)\b", low) and amount:
        src = _grab(rf"\bfrom\s+(.+?){_STOP}", text)
        dst = _grab(rf"\b(?:to|into)\s+(.+?){_STOP}", text)
        if src and dst:
            return {
                "intent": "transfer",
                "amount": amount,
                "account": _clean_account(src),
                "to_account": _clean_account(dst),
            }

    if re.search(r"\b(balance|net worth|how much (?:money )?do i have|my accounts?)\b", low):
        return {"intent": "balance"}

    if re.search(
        r"\b(reduce|cut|save|saving|savings|advice|tips?|subscriptions?|budget|overspend)", low
    ):
        return {"intent": "advice"}

    if re.search(
        r"\b(report|summary|summari[sz]e|breakdown|how much (?:did|have) i (?:spend|spent)|spending)\b",
        low,
    ):
        return {"intent": "report", "category": categorize(text)}

    if amount and re.search(
        r"\b(received|got|earned|salary|credited|income|deposited|refund(?:ed)?)\b", low
    ):
        account = _grab(rf"\b(?:in|into|to|via)\s+(.+?){_STOP}", text)
        source = _grab(rf"\bfrom\s+(.+?){_STOP}", text)
        category = categorize(text) or ("Salary" if "salary" in low else "Income")
        return {
            "intent": "income",
            "amount": amount,
            "account": _clean_account(account),
            "category": category,
            "merchant": source.title() if source else None,
            "description": text,
        }

    if amount and re.search(
        r"\b(spent|paid|pay|bought|buy|purchase[d]?|debited|cost|ordered)\b", low
    ):
        account = _grab(rf"\b(?:via|using|with|through|from|by)\s+(.+?){_STOP}", text)
        merchant = _grab(rf"\b(?:to|at)\s+(.+?){_STOP}", text)
        what = _grab(rf"\b(?:on|for)\s+(?:a |an |the |my )?(.+?){_STOP}", text)
        category = categorize(merchant, what, text) or (what.title() if what else None)
        result = {
            "intent": "expense",
            "amount": amount,
            "account": _clean_account(account),
            "merchant": merchant.title() if merchant else None,
            "category": category,
            "description": text,
        }
        if result["merchant"] and re.fullmatch(r"(?i)(cash|bank|upi|card)", result["merchant"]):
            result["merchant"] = None
        return result

    return result


# ---------------------------------------------------------------------------
# Statement parsing (PhonePe / GPay / bank PDFs and forwarded SMS text)
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"\b([A-Z][a-z]{2,8})\s+(\d{1,2}),?\s+(\d{4})\b"), "%b %d %Y"),
    (re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]{2,8})\.?,?\s+(\d{4})\b"), "%d %b %Y"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y %m %d"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), "%d %m %Y"),
]
_AMOUNT_LINE = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_CREDIT_WORDS = re.compile(r"\b(credit|credited|received(?: from)?|refund|cashback)\b", re.I)
_DEBIT_WORDS = re.compile(r"\b(debit|debited|paid(?: to)?|sent to|purchase|spent)\b", re.I)
_PAYEE = re.compile(
    r"(?:paid to|received from|sent to|transfer to|transfer from|to|from|at|info:?)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 &.'@_-]{1,40}?)(?=\s+(?:debit|credit|₹|rs\.?|inr|on|ref|utr|txn|transaction)\b|$)",
    re.I,
)


def _find_date(line: str) -> datetime | None:
    for rx, fmt in _DATE_PATTERNS:
        m = rx.search(line)
        if not m:
            continue
        parts = " ".join(m.groups())
        for f in (fmt, fmt.replace("%b", "%B")):
            try:
                return datetime.strptime(parts, f)
            except ValueError:
                continue
    return None


def _extract_pdf_text(file_bytes: bytes) -> str:
    if len(file_bytes) > MAX_PDF_BYTES:
        raise ValueError("PDF is too large (max 10 MB)")
    if not file_bytes.startswith(b"%PDF"):
        raise ValueError("File is not a valid PDF")
    from PyPDF2 import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        raise ValueError("PDF is password protected")
    pages = reader.pages[:MAX_PDF_PAGES]
    return "\n".join((p.extract_text() or "") for p in pages)


def parse_statement_text(text: str) -> list[dict[str, Any]]:
    """Turns statement text into transactions. A block starts at each line containing a date."""
    blocks: list[tuple[datetime, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        date = _find_date(line)
        if date:
            blocks.append((date, [line]))
        elif blocks:
            blocks[-1][1].append(line)

    out: list[dict[str, Any]] = []
    for date, lines in blocks:
        blob = " ".join(lines)
        amt = _AMOUNT_LINE.search(blob)
        if not amt:
            continue
        credit = bool(_CREDIT_WORDS.search(blob))
        debit = bool(_DEBIT_WORDS.search(blob))
        if not credit and not debit:
            continue
        # "Received from X" is credit even though "paid" may appear elsewhere
        tx_type = "income" if credit and not re.search(r"\bdebit\b", blob, re.I) else "expense"
        payee = _PAYEE.search(blob)
        merchant = payee.group(1).strip(" .") if payee else None
        try:
            amount = float(amt.group(1).replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue
        out.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "merchant": merchant.title() if merchant else "Unknown",
                "type": tx_type,
                "amount": amount,
                "category": categorize(merchant, blob),
                "raw": blob[:200],
            }
        )
    return out


async def parse_statement_file(file_bytes: bytes, file_type: str = "pdf") -> list[dict]:
    """Parses a PhonePe / bank statement (pdf) or forwarded SMS/plain text (txt)."""
    kind = file_type.lower().lstrip(".")
    if kind == "pdf":
        text = await asyncio.to_thread(_extract_pdf_text, file_bytes)
    elif kind in ("txt", "text", "sms"):
        text = file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
    return parse_statement_text(text)


def import_parsed_transactions(
    db, user_id: str, items: list[dict[str, Any]], account_name: str = "Bank"
) -> dict[str, int]:
    """Records parsed statement rows, skipping ones already imported (same day/amount/merchant)."""
    imported = skipped = failed = 0
    existing = {
        (t.created_at.date().isoformat(), round(t.amount, 2), (t.description or "").lower())
        for t in ledger.list_transactions(db, user_id, days=3650)
        if t.source == "pdf"
    }
    for it in items:
        desc = f"{it['merchant']} (statement)"
        sig = (it["date"], round(float(it["amount"]), 2), desc.lower())
        if sig in existing:
            skipped += 1
            continue
        try:
            ledger.record_transaction(
                db,
                user_id,
                amount=it["amount"],
                account_name=account_name,
                category_name=it.get("category") or ("Income" if it["type"] == "income" else None),
                merchant_name=None if it["merchant"] == "Unknown" else it["merchant"],
                tx_type=it["type"],
                description=desc,
                source="pdf",
                created_at=datetime.strptime(it["date"], "%Y-%m-%d"),
            )
            existing.add(sig)
            imported += 1
        except ledger.LedgerError:
            failed += 1
    return {"imported": imported, "skipped_duplicates": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def detect_recurring(db, user_id: str, days: int = 120) -> list[dict[str, Any]]:
    """Merchants charged in 2+ different months with a near-constant amount."""
    groups: dict[str, list] = {}
    for t in ledger.list_transactions(db, user_id, days=days, tx_type="expense"):
        key = t.merchant.name if t.merchant else None
        if key:
            groups.setdefault(key, []).append(t)
    found = []
    for name, txs in groups.items():
        months = {(t.created_at.year, t.created_at.month) for t in txs}
        amounts = [t.amount for t in txs]
        if len(months) >= 2 and max(amounts) <= min(amounts) * 1.1:
            avg = sum(amounts) / len(amounts)
            found.append(
                {
                    "merchant": name,
                    "category": txs[0].category.name if txs[0].category else None,
                    "avg_amount": round(avg, 2),
                    "occurrences": len(txs),
                    "monthly_cost": round(avg, 2),
                    "yearly_cost": round(avg * 12, 2),
                }
            )
    return sorted(found, key=lambda r: -r["avg_amount"])


def generate_financial_insights(user_id: str, mode: str = "summary") -> dict:
    """mode='summary' -> where most was spent; mode='reduce' -> actionable cut suggestions."""
    with SessionLocal() as db:
        summary = ledger.get_spending_summary(db, user_id, days=30)
        top_categories = list(summary["category_breakdown"].items())[:5]
        top_merchants = list(summary["merchant_breakdown"].items())[:5]
        result: dict[str, Any] = {
            "mode": mode,
            "period_days": 30,
            "total_expenses": summary["total_expenses"],
            "top_categories": top_categories,
            "top_merchants": top_merchants,
        }
        if mode != "reduce":
            return result

        total = summary["total_expenses"] or 1.0
        tips = []
        for cat, amt in top_categories:
            if cat in DISCRETIONARY and amt / total >= 0.2:
                saving = round(amt * 0.2, 2)
                tips.append(
                    {
                        "category": cat,
                        "spent": amt,
                        "tip": f"{cat} is {amt / total:.0%} of your spend. Trimming it by 20% saves ₹{saving:,.0f}/month.",
                        "potential_monthly_saving": saving,
                    }
                )
        recurring = detect_recurring(db, user_id)
        for r in recurring:
            if r.get("category") in ESSENTIAL:  # don't suggest cancelling rent / utilities
                continue
            tips.append(
                {
                    "category": "Subscription",
                    "spent": r["avg_amount"],
                    "tip": f"{r['merchant']} recurs at ~₹{r['avg_amount']:,.0f}/month (₹{r['yearly_cost']:,.0f}/year). Still using it?",
                    "potential_monthly_saving": r["avg_amount"],
                }
            )
        result["recurring"] = recurring
        result["tips"] = tips
        result["potential_monthly_saving"] = round(
            sum(t["potential_monthly_saving"] for t in tips), 2
        )
        return result
