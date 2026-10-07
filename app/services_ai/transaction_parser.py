"""Offline-first statement/receipt ingestion and financial insights for Role 5."""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Category, Merchant, Transaction

_AMOUNT = r"(?:(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.\d{1,2})?)|(?:amount|spent|paid|debited|credited)\D{0,15}?([0-9][0-9,]*(?:\.\d{1,2})?))"
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y")


def _clean_merchant(value: str) -> str:
    value = re.sub(r"\bUPI[-/:]?", "", value, flags=re.I)
    value = re.sub(r"\b\d{6,}\b", "", value)
    value = re.sub(r"[@#].*$", "", value).replace("-", " ")
    value = re.sub(
        r"\b(?:payment|pay|to|from|ref(?:erence)?|txn|transfer|via)\b", " ", value, flags=re.I
    )
    value = re.sub(r"\s+", " ", value).strip(" .,:;|-")
    return value.title() if value else "Unknown"


def categorize_transaction(
    merchant: str,
    description: str = "",
    tx_type: str = "expense",
    *,
    user_id: str | None = None,
    db: Session | None = None,
) -> str:
    """Classify from that user's prior confirmed transactions, never a fixed merchant list.

    A category is learned whenever the ledger records a merchant/category pair.
    New merchants deliberately remain ``Uncategorized`` until the user confirms
    one, preventing a misleading guess from becoming financial data.
    """
    if tx_type == "income":
        return "Income"
    if not user_id or db is None or merchant == "Unknown":
        return "Uncategorized"
    normalized = merchant.casefold().strip()
    learned = (
        db.execute(
            select(Category.name)
            .join(Merchant, Merchant.default_category_id == Category.id)
            .where(Merchant.user_id == user_id, func.lower(Merchant.name) == normalized)
        )
        .scalars()
        .first()
    )
    if learned:
        return learned
    # Supports older ledger rows where the merchant did not yet have a default.
    return (
        db.execute(
            select(Category.name)
            .join(Transaction, Transaction.category_id == Category.id)
            .join(Merchant, Transaction.merchant_id == Merchant.id)
            .where(Merchant.user_id == user_id, func.lower(Merchant.name) == normalized)
            .order_by(Transaction.created_at.desc())
        )
        .scalars()
        .first()
        or "Uncategorized"
    )


def _parse_date(value: str) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_receipt_text(
    text: str, *, user_id: str | None = None, db: Session | None = None
) -> list[dict[str, Any]]:
    """Parse forwarded bank SMS text, receipt text, or one statement row."""
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines() or [text]:
        line = " ".join(raw_line.split())
        amount_match = re.search(_AMOUNT, line, re.I)
        if not line or not amount_match:
            continue
        debit = re.search(r"\b(debited|debit|paid|spent|withdrawn|dr)\b", line, re.I)
        credit = re.search(r"\b(credited|credit|received|deposit|salary|cr)\b", line, re.I)
        tx_type = "income" if credit and not debit else "expense"
        date_match = re.search(
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
            line,
        )
        merchant_match = re.search(
            r"\b(?:to|at|merchant|paid to|from)\s+(.+?)(?:\s+(?:on|ref|txn|avl|a/c|account)\b|$)",
            line,
            re.I,
        )
        merchant = _clean_merchant(
            merchant_match.group(1) if merchant_match else line[: amount_match.start()]
        )
        account_match = re.search(
            r"\b(?:a/c|account)\s*(?:no\.?|ending)?\s*([xX*\d-]{4,})", line, re.I
        )
        vpa_match = re.search(r"\b([\w.+-]+@[\w.-]+)\b", line)
        rows.append(
            {
                "date": _parse_date(date_match.group(1)) if date_match else None,
                "merchant": merchant,
                "vpa": vpa_match.group(1) if vpa_match else None,
                "type": tx_type,
                "amount": float(
                    next(group for group in amount_match.groups() if group).replace(",", "")
                ),
                "bank_account": account_match.group(1) if account_match else None,
                "category": categorize_transaction(merchant, line, tx_type, user_id=user_id, db=db),
                "description": line,
                "source": "sms",
            }
        )
    return rows


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from PyPDF2 import PdfReader

        return "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(file_bytes)).pages
        )
    except Exception as exc:
        raise ValueError(
            "Could not read PDF text. Upload a text-based PDF or receipt text."
        ) from exc


async def parse_statement_file(
    file_bytes: bytes,
    file_type: str = "pdf",
    *,
    user_id: str | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Parse a PDF statement or text/SMS receipt into normalized transaction rows."""
    if not file_bytes:
        raise ValueError("The uploaded file is empty.")
    file_type = file_type.lower().lstrip(".")
    if file_type == "pdf":
        text, source = _extract_pdf_text(file_bytes), "pdf"
    elif file_type in {"text", "txt", "sms", "receipt"}:
        text, source = file_bytes.decode("utf-8", errors="replace"), "sms"
    else:
        raise ValueError("Unsupported file type. Use pdf or text/SMS receipt content.")
    rows = parse_receipt_text(text, user_id=user_id, db=db)
    for row in rows:
        row["source"] = source
    return rows


def parse_phonepe_pdf(
    file_bytes: bytes, *, user_id: str | None = None, db: Session | None = None
) -> list[dict[str, Any]]:
    """Backward-compatible synchronous PhonePe PDF parser."""
    return parse_receipt_text(_extract_pdf_text(file_bytes), user_id=user_id, db=db)


def parse_chat_expense(
    text: str, *, user_id: str | None = None, db: Session | None = None
) -> dict[str, Any] | None:
    """Extract one expense/income from a short chat message without an LLM."""
    rows = parse_receipt_text(text, user_id=user_id, db=db)
    return rows[0] if rows else None


def _insights_for_session(db: Session, user_id: str) -> dict[str, Any]:
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id, Transaction.transaction_type == "expense"
            )
        )
    )
    category_names = dict(
        db.execute(select(Category.id, Category.name).where(Category.user_id == user_id)).all()
    )
    merchant_names = dict(
        db.execute(select(Merchant.id, Merchant.name).where(Merchant.user_id == user_id)).all()
    )
    category_totals: dict[str, float] = defaultdict(float)
    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_entries: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        category_totals[category_names.get(tx.category_id, "Uncategorized")] += tx.amount
        merchant = merchant_names.get(tx.merchant_id, "Unknown")
        merchant_totals[merchant] += tx.amount
        merchant_entries[merchant].append(tx)
    total = sum(category_totals.values())
    recurring = []
    for merchant, entries in merchant_entries.items():
        amounts = [entry.amount for entry in entries]
        if (
            merchant != "Unknown"
            and len(entries) >= 2
            and max(amounts) - min(amounts) <= max(amounts) * 0.1
        ):
            recurring.append(
                {
                    "merchant": merchant,
                    "amount": round(sum(amounts) / len(amounts), 2),
                    "occurrences": len(entries),
                }
            )
    categories = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    tips = []
    for category, amount in categories[:3]:
        share = amount / total if total else 0
        if share >= 0.2:
            tips.append(
                f"{category} is {share:.0%} of recorded spending (₹{amount:,.2f}); set a weekly cap."
            )
    tips.extend(
        f"Review recurring {item['merchant']} charge of about ₹{item['amount']:,.2f}."
        for item in recurring
    )
    return {
        "total_expenses": round(total, 2),
        "transaction_count": len(transactions),
        "top_categories": [{"category": n, "amount": round(a, 2)} for n, a in categories[:5]],
        "top_merchants": [
            {"merchant": n, "amount": round(a, 2)}
            for n, a in sorted(merchant_totals.items(), key=lambda i: i[1], reverse=True)[:5]
        ],
        "recurring_subscriptions": sorted(recurring, key=lambda item: item["amount"], reverse=True),
        "reduce_money_tips": tips
        or ["Record more expenses to receive personalized savings suggestions."],
    }


def generate_financial_insights(
    user_id: str, mode: str = "summary", db: Session | None = None
) -> dict[str, Any]:
    """Return top spending, recurring-charge, and actionable savings insights."""
    if mode not in {"summary", "reduce_money"}:
        raise ValueError("mode must be 'summary' or 'reduce_money'")
    owns_session = db is None
    db = db or SessionLocal()
    try:
        result = _insights_for_session(db, user_id)
        result["mode"] = mode
        return result
    finally:
        if owns_session:
            db.close()
