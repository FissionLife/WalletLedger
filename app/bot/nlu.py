"""Rule-based understanding of chat messages. Instant, free, and predictable.

The agent tries this FIRST. When a message is clear (an amount plus what it was for), it is handled
here with no AI call; anything else falls through to the AI (or a short help message when the user
has no AI key). Two kinds of result:

    parse_entries(text, ctx)  -> list[Entry]   "Spent 200 on chai, 80 on auto and 1200 on groceries"
    detect_screen(text)       -> Screen        "how much did I spend on food last month" -> /stats food last month

Nothing here touches the database: the caller passes the user's known account / merchant names
(`Context`) so "via hdfc" matches "HDFC Bank".
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app import clock

# --------------------------------------------------------------------------------------- types


@dataclass
class Context:
    """What we know about the user, to resolve names. All optional."""

    accounts: list[str] = field(default_factory=list)
    merchants: list[str] = field(default_factory=list)
    default_expense_account: str = "Cash"
    default_income_account: str = "Bank"
    today: date | None = None


@dataclass
class Entry:
    kind: str  # expense | income | transfer
    amount: float
    account: str | None = None
    to_account: str | None = None  # transfers
    category: str | None = None
    merchant: str | None = None
    note: str = ""
    when: str | None = None  # ISO date, only when the user named a day


@dataclass
class Screen:
    command: str  # /stats /balance /history /undo /budget /dashboard /export /help
    args: str = ""


# ------------------------------------------------------------------------------------ amounts

_NUM = r"\d[\d,]*(?:\.\d+)?"
_MONEY = re.compile(
    rf"(?<![\w.:/#-])(?:(?:₹|rs\.?|inr)\s*)?({_NUM})\s*(k|lakhs?|lacs?|crores?|cr|l)?"
    rf"(?:\s*(?:/-|rs\b\.?|inr\b|rupees?\b))?(?![\w:/%-]|\.\d)",
    re.I,
)
_MULT = {"k": 1_000, "l": 100_000, "lac": 100_000, "lacs": 100_000, "lakh": 100_000, "lakhs": 100_000,
         "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000}  # fmt: skip


def _plausible(m: re.Match) -> bool:
    """Reject phone numbers and ids: 8+ plain digits with no comma, decimal point or k/l/cr suffix."""
    digits = m.group(1)
    return not (len(digits) >= 8 and digits.isdigit() and not m.group(2))


def parse_amount(text: str) -> float | None:
    """ "6000", "6k", "2l", "1.5 lakh", "₹6,000" -> 6000.0 ... ; None if it is not just an amount."""
    m = _MONEY.fullmatch((text or "").strip())
    if not m or not _plausible(m):
        return None
    value = _to_amount(m.group(1), m.group(2))
    return value if value > 0 else None


def _to_amount(num: str, suffix: str | None) -> float:
    value = float(num.replace(",", ""))
    return round(value * _MULT.get((suffix or "").lower(), 1), 2)


# -------------------------------------------------------------------------------------- dates

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}  # fmt: skip


def extract_date(text: str, today: date | None = None) -> tuple[str | None, str]:
    """Find a day named in the text. Returns (ISO date or None, text without the date words)."""
    today = today or clock.today_local()
    t = text

    def cut(m: re.Match) -> str:
        return (t[: m.start()] + " " + t[m.end() :]).strip()

    m = re.search(r"\bday before yesterday\b", t, re.I)
    if m:
        return (today - timedelta(days=2)).isoformat(), cut(m)
    m = re.search(r"\b(yesterday|last night)\b", t, re.I)
    if m:
        return (today - timedelta(days=1)).isoformat(), cut(m)
    m = re.search(r"\b(today|tonight|this morning|this evening)\b", t, re.I)
    if m:
        return today.isoformat(), cut(m)
    m = re.search(r"\b(\d{1,3})\s+days?\s+(?:ago|back)\b", t, re.I)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat(), cut(m)
    m = re.search(r"\b(aaj)\b", t, re.I)
    if m:
        return today.isoformat(), cut(m)
    m = re.search(r"\b(parso|parsoon)\b", t, re.I)
    if m:
        return (today - timedelta(days=2)).isoformat(), cut(m)
    m = re.search(r"\b(kal)\b", t, re.I)  # when logging what was spent, "kal" means yesterday
    if m:
        return (today - timedelta(days=1)).isoformat(), cut(m)
    m = re.search(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), cut(m)
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m and not re.search(r"\d[/-]\d{1,2}[/-]\d{1,2}[/-]", t):
        d, mo = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        year += 2000 if year < 100 else 0
        try:
            found = date(year, mo, d)
            if not m.group(3) and found > today:
                found = date(year - 1, mo, d)
            return found.isoformat(), cut(m)
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", t)  # 05.10.2026
    if m:
        year = int(m.group(3)) + (2000 if int(m.group(3)) < 100 else 0)
        try:
            return date(year, int(m.group(2)), int(m.group(1))).isoformat(), cut(m)
        except ValueError:
            pass
    months = "|".join(_MONTHS)
    year_tail = r"(?:\s*,?\s*['’]?(\d{2,4}))?"
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})[a-z]*\.?{year_tail}\b", t, re.I)
    year_txt = None
    if not m:
        m2 = re.search(
            rf"\b({months})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?{year_tail}\b", t, re.I
        )
        if m2:
            day, mon, year_txt = int(m2.group(2)), m2.group(1), m2.group(3)
            m = m2
        else:
            day = mon = None
    else:
        day, mon, year_txt = int(m.group(1)), m.group(2), m.group(3)
    if m and day and mon:
        try:
            if year_txt:
                year = int(year_txt) + (2000 if int(year_txt) < 100 else 0)
                return date(year, _MONTHS[mon.lower()[:3]], day).isoformat(), cut(m)
            found = date(today.year, _MONTHS[mon.lower()[:3]], day)
            if found > today:
                found = date(today.year - 1, found.month, found.day)
            return found.isoformat(), cut(m)
        except ValueError:
            pass
    m = re.search(rf"\b(?:on |last )?({'|'.join(_WEEKDAYS)})\b", t, re.I)
    if m:
        back = (today.weekday() - _WEEKDAYS.index(m.group(1).lower())) % 7 or 7
        return (today - timedelta(days=back)).isoformat(), cut(m)
    m = re.search(r"\bon the (\d{1,2})(?:st|nd|rd|th)\b|\bon (\d{1,2})(?:st|nd|rd|th)\b", t, re.I)
    if m:
        day = int(m.group(1) or m.group(2))
        try:
            found = date(today.year, today.month, day)
            if found > today:
                prev = today.replace(day=1) - timedelta(days=1)
                found = date(prev.year, prev.month, min(day, prev.day))
            return found.isoformat(), cut(m)
        except ValueError:
            pass
    return None, text


# ---------------------------------------------------------------------------------- vocabulary

_INCOME = re.compile(
    r"\b(received|earned|credited|salary|stipend|stifend|refund(?:ed)?|cashback|income|bonus|"
    r"dividend|reimburse\w*|freelance|got paid|payout|pocket money|pension|sold|won|deposit(?:ed)?)\b"
    r"|\bgot\s+(?:a\s+|an\s+)?(?:₹|rs\.?\s*|inr\s*)?\d"  # "got 5000 from dad" (not "got petrol 500")
    r"|\b(?:paid|gave|sent|returned|transferred|lent|refunded)\s+(?:me|back)\b"  # "ravi paid me 500"
    r"|\b(?:gift|rent|money|payment|amount)\s+from\b",
    re.I,
)
# Things that are not a transaction the user is reporting: plans, reminders, negations, facts about money
_NOT_A_TRANSACTION = re.compile(
    r"\b(?:remind(?:\s+me)?|will|won'?t|would|going\s+to|gonna|planning\s+to|plan\s+to|want\s+to|wanna|"
    r"need\s+to|should|if\s+i|didn'?t|did\s+not|never|haven'?t|have\s+not|not\s+(?:paid|spent|received)|"
    r"owes?\s+me|i\s+owe|my\s+salary\s+is|salary\s+is)\b",
    re.I,
)
_UNPARSED_DATE = re.compile(
    r"\b(?:last|next|this)\s+(?:week|month|year)\b|\btomorrow\b|\bnext\s+(?:mon|tue|wed|thu|fri|sat|sun)\w*",
    re.I,
)
_KNOWN_BANKS = {
    "hdfc", "sbi", "icici", "axis", "kotak", "idfc", "yes", "pnb", "bob", "canara", "union", "indusind",
    "rbl", "federal", "hsbc", "citi", "amex", "au", "bandhan", "idbi", "boi", "savings", "salary", "current",
}  # fmt: skip
_TRANSFER = re.compile(
    r"\b(transfer(?:red)?|moved?|shift(?:ed)?|sent myself|top(?:ped)?[- ]?up)\b", re.I
)
_WITHDRAW = re.compile(r"\b(withdr[ae]w|withdrawn|atm)\b", re.I)
_DEPOSIT_CASH = re.compile(r"\bdeposit(?:ed)?\b.*\bcash\b|\bcash\b.*\bdeposit(?:ed)?\b", re.I)
_EXPENSE = re.compile(
    r"\b(spent|spend|paid|pay|bought|buy|purchased?|ordered|cost|gave|donated?|recharged?|"
    r"rented|charged|lost|fine[d]?)\b",
    re.I,
)
_SPLIT = re.compile(
    r"\n|;|(?<!\d),|,(?!\d)|\band then\b|\bthen\b|\balso\b|\band\b|\bplus\b|\+", re.I
)
_STOP_AFTER = r"(?=\s+(?:for|via|using|through|on|in|into|with|and|by|at|from|to|yesterday|today)\b|[,.;!?]|\d|$)"

_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "Food & Dining": (
        "chai", "tea", "coffee", "lunch", "dinner", "breakfast", "brunch", "snack", "snacks", "food",
        "meal", "pizza", "burger", "biryani", "dosa", "idli", "idly", "thali", "ice cream", "juice",
        "restaurant", "cafe", "canteen", "mess", "takeaway", "bakery", "sweets", "dessert", "drinks",
        "beer", "bar", "paratha", "samosa", "maggi", "momos", "sandwich", "roll",
    ),
    "Groceries": (
        "grocery", "groceries", "vegetables", "veggies", "fruits", "milk", "eggs", "rice", "atta",
        "dal", "kirana", "supermarket", "provisions", "bread", "curd",
    ),
    "Transport": (
        "auto", "cab", "taxi", "uber", "ola", "rapido", "metro", "bus", "train", "ticket", "petrol",
        "diesel", "fuel", "toll", "parking", "fastag", "flight", "ride", "commute",
    ),
    "Shopping": (
        "clothes", "shirt", "shoes", "shopping", "dress", "jeans", "bag", "watch", "gift", "laptop",
        "phone", "mobile", "headphones", "gadget", "furniture", "amazon", "flipkart", "myntra",
    ),
    "Entertainment": ("movie", "movies", "cinema", "netflix", "spotify", "hotstar", "prime", "game", "games", "concert", "show", "subscription"),
    "Bills & Utilities": ("electricity", "current bill", "water bill", "gas", "wifi", "internet", "broadband", "recharge", "bill", "postpaid", "dth", "maintenance"),
    "Rent": ("rent",),
    "Health": ("medicine", "medicines", "pharmacy", "doctor", "hospital", "clinic", "gym", "lab test", "dentist", "checkup", "health"),
    "Personal Care": ("haircut", "salon", "spa", "grooming", "shampoo", "parlour", "barber", "facial"),
    "Education": ("course", "tuition", "books", "fees", "exam", "class", "school", "college"),
    "Investments": ("sip", "mutual fund", "stocks", "investment", "invested", "fd", "ppf"),
    "Travel": ("hotel", "trip", "vacation", "holiday", "resort", "booking"),
}  # fmt: skip
_INCOME_CATEGORY = {
    "salary": "Salary", "stipend": "Salary", "pay ?check": "Salary", "pension": "Salary",
    "freelance": "Freelance", "refund": "Refund", "cashback": "Cashback", "bonus": "Bonus",
    "dividend": "Investments", "interest": "Interest", "reimburse": "Reimbursement",
}  # fmt: skip
_ACCOUNT_WORDS = {"cash": "Cash", "bank": "Bank", "card": "Credit Card", "credit card": "Credit Card",
                  "debit card": "Bank", "upi": "UPI", "gpay": "UPI", "phonepe": "UPI", "paytm": "UPI",
                  "google pay": "UPI", "netbanking": "Bank", "wallet": "Wallet"}  # fmt: skip

_FILLER = {
    "a",
    "an",
    "the",
    "my",
    "some",
    "of",
    "to",
    "for",
    "on",
    "in",
    "at",
    "with",
    "from",
    "i",
    "me",
    "just",
    "about",
    "around",
    "approx",
    "got",
    "get",
    "had",
    "have",
    "took",
    "take",
    "this",
    "that",
}


def _word_re(word: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", re.I)


def _resolve_account(phrase: str | None, ctx: Context) -> str | None:
    """Map free text ('hdfc', 'my card', 'cash') to one of the user's accounts or a standard name."""
    if not phrase:
        return None
    p = phrase.strip().lower()
    for name in ctx.accounts:
        if p == name.lower():
            return name
    partial = [n for n in ctx.accounts if len(p) >= 3 and (p in n.lower() or n.lower() in p)]
    if partial:
        return max(
            partial, key=len
        )  # "hdfc bank" is the HDFC account, not the account called "Bank"
    for word, std in _ACCOUNT_WORDS.items():
        if p == word:
            if std == "UPI":
                match = next(
                    (a for a in ctx.accounts if "upi" in a.lower() or "wallet" in a.lower()), None
                )
                bank = next(
                    (a for a in ctx.accounts if not re.search(r"cash|card|credit", a, re.I)), None
                )
                return match or bank or "Bank"  # UPI payments leave the user's bank account
            match = next((a for a in ctx.accounts if std.lower() in a.lower()), None)
            return match or std
    # A new account is only made for something that looks like one (a bank or an "... bank/card/wallet"):
    # "from ravi" or "from atm" is a person or a machine, not an account with a balance of its own.
    first = p.split()[0] if p.split() else ""
    looks_like_account = first in _KNOWN_BANKS or bool(
        re.search(r"\b(?:bank|card|wallet|account|savings)\b", p)
    )
    if looks_like_account and re.fullmatch(r"[A-Za-z][A-Za-z &.-]{1,24}", phrase.strip()):
        return phrase.strip().title()
    return None


def _find_known_account(text: str, ctx: Context) -> str | None:
    for name in sorted(ctx.accounts, key=len, reverse=True):
        if _word_re(name).search(text):
            return name
    return None


def _account_phrase(text: str, kind: str, ctx: Context) -> str | None:
    known = _find_known_account(text, ctx)
    if known:
        return known
    pattern = r"\b(?:via|using|through|by|with)\s+(?:my\s+|the\s+)?([A-Za-z][\w&.-]*(?:\s+(?:bank|card|wallet|account|pay))?)"
    if kind == "income":
        pattern = r"\b(?:in|into|to|via|using|through)\s+(?:my\s+|the\s+)?([A-Za-z][\w&.-]*(?:\s+(?:bank|card|wallet|account))?)"
    elif kind == "expense":
        pattern += (
            r"|\bfrom\s+(?:my\s+|the\s+)?([A-Za-z][\w&.-]*(?:\s+(?:bank|card|wallet|account))?)"
        )
    for m in re.finditer(pattern, text, re.I):
        phrase = next((g for g in m.groups() if g), "")
        phrase = re.sub(r"\s+(account|acc)$", "", phrase, flags=re.I)
        resolved = _resolve_account(phrase, ctx)
        if resolved and not (kind == "income" and phrase.lower() in ("freelance", "salary")):
            return resolved
    for word in (
        "credit card",
        "debit card",
        "cash",
        "upi",
        "gpay",
        "phonepe",
        "paytm",
        "google pay",
        "netbanking",
    ):
        if _word_re(word).search(text):
            return _resolve_account(word, ctx)
    return None


def _clean_what(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&'-]*", text) if w.lower() not in _FILLER]
    return " ".join(words).strip()


def _category_for(kind: str, what: str, clause: str, merchant: str | None) -> str | None:
    low = f" {what.lower()} {clause.lower()} "
    if kind == "income":
        for key, cat in _INCOME_CATEGORY.items():
            if re.search(rf"\b{key}", low):
                return cat
        return "Income"
    best = None
    for cat, words in _CATEGORY_WORDS.items():
        for w in words:
            matched = re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)
            if matched and (best is None or len(w) > best[1]):  # the most specific word wins
                best = (cat, len(w))
    if best:
        return best[0]
    # a typo in the item ("lnch", "cofee"): the closest known word, if it is close enough
    known = {
        w: cat
        for cat, words in _CATEGORY_WORDS.items()
        for w in words
        if " " not in w and len(w) >= 4
    }
    for token in re.findall(r"[a-z]{4,}", low):
        close = difflib.get_close_matches(token, known, n=1, cutoff=0.8)
        if close:
            return known[close[0]]
    try:
        from app.services_ai.transaction_parser import categorize_transaction

        hit = categorize_transaction(merchant or "", clause)
        if hit and hit not in ("Uncategorized", "Transfers"):
            return hit
    except Exception:  # the parser is optional here
        pass
    words = what.split()
    after_on_for = (
        re.search(rf"\b(?:on|for)\s+(?:\w+\s+){{0,2}}{re.escape(what.split()[0])}\b", clause, re.I)
        if what
        else None
    )
    if what and len(words) <= 2 and all(w.isalpha() for w in words) and after_on_for:
        return what.title()  # "spent 300 on pottery" is a real item; a stray word is not a category
    return None


_NOT_AN_ITEM = re.compile(
    r"\b(balance|budget|stats|report|history|undo|how|what|why|when|where|who|which|show|set|"
    r"i|we|you|he|she|they|is|are|was|were|have|has|had|will|can|do|does|did|plus|minus|times|"
    r"divided|call|meet|meeting|remind|id|otp|code|number|phone|there|here|this|that)\b",
    re.I,
)


_WAS_COST = re.compile(
    r"^(?!(?:it|that|this|there|balance|total|salary|income|bill is|amount)\b)[a-z][a-z&' -]{1,24}\s+(?:was|were|cost|costs|came to)\s+"
    r"(?:about |around |roughly |only |just )?(?:₹|rs\.?\s*|inr\s*)?\d"
)


def _short_item(text: str) -> bool:
    """A short 'thing + amount' fragment such as 'chai 20' (no verb, not a question)."""
    if "?" in text or len(text.split()) > 5:
        return False
    if not re.findall(r"[A-Za-z]{3,}", _MONEY.sub(" ", text)):
        return False
    return not _NOT_AN_ITEM.search(text)


# ---------------------------------------------------------------------------------- one clause


def _parse_clause(raw: str, ctx: Context, inherit_kind: str | None) -> Entry | None:
    when, text = extract_date(raw, ctx.today)
    if when is None and _UNPARSED_DATE.search(text):
        return None  # "last week", "tomorrow": ask rather than record it on the wrong day
    amounts = [(m, _to_amount(m.group(1), m.group(2))) for m in _money_matches(text)]
    amounts = [(m, a) for m, a in amounts if 0 < a <= 1_000_000_000]
    if not amounts:
        return None
    m, amount = amounts[0]
    low = text.lower()

    transfer = (
        bool(_TRANSFER.search(text))
        or bool(_WITHDRAW.search(text))
        or bool(_DEPOSIT_CASH.search(text))
    )
    if transfer:
        src = dst = None
        mf = re.search(
            r"\bfrom\s+(?:my\s+|the\s+)?([A-Za-z][\w&.-]*(?:\s+(?:bank|card|wallet|account))?)",
            text,
            re.I,
        )
        mt = re.search(
            r"\b(?:to|into|in)\s+(?:my\s+|the\s+)?([A-Za-z][\w&.-]*(?:\s+(?:bank|card|wallet|account))?)",
            text,
            re.I,
        )
        if mf:
            src = _resolve_account(re.sub(r"\s+(account|acc)$", "", mf.group(1), flags=re.I), ctx)
        if mt:
            dst = _resolve_account(re.sub(r"\s+(account|acc)$", "", mt.group(1), flags=re.I), ctx)
        if _WITHDRAW.search(text) and not dst:
            dst = _resolve_account("cash", ctx)
            src = src or ctx.default_income_account
        if _DEPOSIT_CASH.search(text) and not src:
            src = _resolve_account("cash", ctx)
            dst = dst or ctx.default_income_account
        if dst and not src:
            src = ctx.default_income_account  # "moved 500 to cash": from the main account
        if src and dst and src.lower() != dst.lower():
            return Entry("transfer", amount, src, dst, note=raw.strip(), when=when)
        return None

    kind = None
    expense_part = re.sub(
        r"\b(?:got paid|(?:paid|gave|sent|returned|transferred|lent|refunded)\s+(?:me|back))\b",
        " ",
        low,
    )  # "got paid 20000" and "ravi paid me 500" are income
    if _INCOME.search(text) and not (
        _EXPENSE.search(expense_part)
        and re.search(r"\b(spent|paid|bought|ordered)\b", expense_part)
    ):
        kind = "income"
    elif _EXPENSE.search(text):
        kind = "expense"
    elif inherit_kind == "expense":
        kind = inherit_kind
    elif re.search(r"\b(on|for)\b", low) or re.search(r"\d\s*(?:at|@)\s+[a-z]", low):
        kind = "expense"  # "450 on dinner" / "450 at Starbucks" with no verb
    elif _short_item(text):
        kind = "expense"  # "chai 20", "190=pizza", "Netflix 649 via credit card"
    elif _WAS_COST.match(re.sub(r"^(?:the|my|our)\s+", "", low)):
        kind = "expense"  # "the rent was 5000", "dinner cost 400"
    if kind is None:
        return None

    account = _account_phrase(text, kind, ctx)

    merchant = None
    for known in sorted(ctx.merchants, key=len, reverse=True):
        if _word_re(known).search(text):
            merchant = known
            break
    if merchant is None:
        who = r"([A-Za-z][\w&'.-]*(?:\s+[A-Za-z][\w&'.-]*)?)"
        lead = r"\bfrom" if kind == "income" else r"\b(?:at|to|@)"
        mm = re.search(rf"{lead}\s+(?:the\s+)?{who}{_STOP_AFTER}", text, re.I)
        if mm:
            cand = mm.group(1).strip()
            names = {a.lower() for a in ctx.accounts}
            if cand.lower() not in _FILLER | _ACCOUNT_WORDS.keys() | names:
                merchant = cand.title() if cand.islower() else cand

    what = ""
    mw = re.search(
        r"\b(?:on|for)\s+(.+?)(?=\s+(?:via|using|through|at|from|with|in|by)\b|[,.;!?]|$)",
        text,
        re.I,
    )
    if mw:
        what = _clean_what(mw.group(1))
    if not what:
        before = text[: m.start()] + " " + text[m.end() :]
        before = re.sub(_EXPENSE.pattern + "|" + _INCOME.pattern, " ", before, flags=re.I)
        what = _clean_what(
            re.sub(r"\b(via|using|through|by|from|into|in|at|to|with)\b.*$", "", before, flags=re.I)
        )

    category = _category_for(kind, what, text, merchant)
    # A brand named as the thing ("spent 300 on Swiggy") is the merchant, not a category word.
    if (
        merchant is None
        and what
        and kind == "expense"
        and what[0].isupper()
        and len(what.split()) <= 2
    ):
        try:
            from app.services_ai.transaction_parser import categorize_transaction

            branded = categorize_transaction(what, "")
            if branded and branded not in ("Uncategorized", "Transfers"):
                merchant, category = what, branded
        except Exception:
            pass

    account = account or (
        ctx.default_income_account if kind == "income" else ctx.default_expense_account
    )
    return Entry(
        kind,
        amount,
        account,
        None,
        category,
        merchant,
        note=raw.strip(),
        when=when,
    )


# --------------------------------------------------------------------------------- whole message


_VERB_START = re.compile(
    r"\b(spent|spend|paid|pay|bought|buy|purchased?|ordered|gave|donated?|received|earned|credited|got|"
    r"transferred?|moved?|withdrew)\b",
    re.I,
)


_DATE_PHRASES = re.compile(
    r"\b\d{1,3}\s+days?\s+(?:ago|back)\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s*,?\s*['’]?\d{2,4}\b)?"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*['’]?\d{2,4}\b)?"
    r"|\b\d{4}/\d{2}/\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b",
    re.I,
)


_COUNTED = re.compile(
    r"\s+(?:[a-z]{2,}s|kgs?|gms?|grams?|litres?|liters?|ml|pcs|pieces|dozen|x)\b", re.I
)


def _quantities(matches: list[re.Match], text: str) -> set[int]:
    """Indexes of small counts that sit next to a bigger amount: the 3 in "3 shirts for 1500"."""
    if len(matches) < 2:
        return set()
    biggest = max(_to_amount(m.group(1), m.group(2)) for m in matches)
    out = set()
    for i, m in enumerate(matches):
        value = _to_amount(m.group(1), m.group(2))
        bare = (
            not m.group(2)
            and "." not in m.group(1)
            and not re.search(r"(?:\u20b9|rs\.?|inr)\s*$", text[: m.start()], re.I)
        )
        if bare and value <= 100 and value < biggest and _COUNTED.match(text, m.end()):
            out.add(i)
    return out


def _money_matches(text: str) -> list[re.Match]:
    """Money amounts in the text, ignoring dates ('5 days ago') and counts ('3 shirts')."""
    spans = [m.span() for m in _DATE_PHRASES.finditer(text)]
    found = [
        m
        for m in _MONEY.finditer(text)
        if _plausible(m) and not any(a <= m.start() < b for a, b in spans)
    ]
    skip = _quantities(found, text)
    return [m for i, m in enumerate(found) if i not in skip]


def _split_multi(clause: str) -> list[str]:
    """Split a clause that holds several amounts ('got 15000 ... spent 190=pizza 80=dosa')."""
    found = _money_matches(clause)
    if len(found) < 2:
        return [clause]
    cuts: list[int] = []
    for prev, nxt in zip(found, found[1:], strict=False):
        gap_start, gap_end = prev.end(), nxt.start()
        gap = clause[gap_start:gap_end]
        verbs = list(_VERB_START.finditer(gap))
        if verbs:
            cuts.append(gap_start + verbs[-1].start())  # "... from that [spend this 190]"
        else:
            sym = re.search(r"(?:\u20b9|rs\.?|inr)\s*$", clause[:gap_end], re.I)
            cuts.append(sym.start() if sym and sym.start() >= gap_start else gap_end)
    pieces, start = [], 0
    for cut in cuts:
        pieces.append(clause[start:cut].strip())
        start = cut
    pieces.append(clause[start:].strip())
    return [piece for piece in pieces if piece]


def split_clauses(text: str) -> list[str]:
    """Split 'a 200 on tea, 80 on auto and 1200 on rent' into clauses that each carry an amount."""
    parts = [p.strip() for p in _SPLIT.split(text) if p and p.strip()]
    clauses: list[str] = []
    for p in parts:
        if _money_matches(p) or not clauses:
            clauses.append(p)
        else:
            clauses[-1] = f"{clauses[-1]} {p}"  # "tea and coffee" has one amount: keep together
    return [piece for clause in clauses for piece in _split_multi(clause)]


_QUESTION_START = re.compile(
    r"^(?:so\s+|and\s+|but\s+|also\s+)?(?:is|are|was|were|am|can|could|should|would|will|shall|do|does|did|"
    r"what|whats|what's|why|how|which|who|whether|any)\b",
    re.I,
)


# "Should I buy ...", "Can I afford ..." always ask, even with a spending verb ("Can't believe I spent" does not)
_ASKING_AUX = re.compile(
    r"^(?:so\s+|and\s+|but\s+|also\s+)?(?:should|can|could|would|will|shall|do|does|did|is|are|am|what\s+if|what\s+about|how\s+about|how\s+much|how\s+many)\b(?!\s*n['’]t)(?!['’]t)",
    re.I,
)


def is_question(text: str) -> bool:
    """ "is 640 too much for dinner?" asks something; it must never be logged as spending."""
    text = (text or "").strip()
    if "?" in text:
        return True
    # a message that starts like a question but states a spend or an income ("Was at Dmart, paid 1500") is not one
    statement = bool(_EXPENSE.search(text) or _INCOME.search(text))
    return any(
        _QUESTION_START.match(c.strip()) and (_ASKING_AUX.match(c.strip()) or not statement)
        for c in split_clauses(text)
    )


_LEADING_MINUS = re.compile(
    r"^\s*[-−–]\s*(?=(?:₹|rs\.?\s*|inr\s*)?\d)", re.I
)  # "-60 chai": money going out


def parse_entries(text: str, ctx: Context | None = None) -> list[Entry]:
    """All transactions in the message, or [] if it does not clearly describe any."""
    ctx = ctx or Context()
    text = (text or "").strip()
    if not text or len(text) > 3000 or is_question(text) or _NOT_A_TRANSACTION.search(text):
        return []
    lines = [_LEADING_MINUS.sub("", line) for line in text.split("\n") if line.strip()]
    per_line = [split_clauses(line) for line in lines]
    clauses = [c for group in per_line for c in group]
    if not clauses or len(clauses) > 40:
        return []
    entries: list[Entry] = []
    inherit: str | None = None
    fresh = {id(group[0]) for group in per_line if group}
    first_of_line = {i for i, c in enumerate(clauses) if id(c) in fresh}
    for index, clause in enumerate(clauses):
        if re.match(r"^\s*(?:grand\s+)?(?:total|sum|subtotal|balance)\b|^\s*=", clause, re.I):
            continue  # "Total 70" at the end of a pasted list is not another purchase
        if index in first_of_line:
            inherit = None  # a new line does not borrow "income" or "expense" from the line above
        entry = _parse_clause(clause, ctx, inherit)
        if entry is None:
            if _money_matches(clause) and re.search(r"[A-Za-z]{3,}", clause):
                return []  # a clause with an amount we could not understand: let the AI look
            continue
        entries.append(entry)
        inherit = entry.kind if entry.kind != "transfer" else inherit
    # "... 80 on auto via Bank": an account named once at the end applies to the items before it
    if len(entries) > 1:
        last_named = next(
            (e.account for e in reversed(entries) if _account_mentioned(e.note, ctx)), None
        )
        if last_named:
            for e in entries:
                if e.kind == "expense" and not _account_mentioned(e.note, ctx):
                    e.account = last_named
    return entries


def _account_mentioned(note: str, ctx: Context) -> bool:
    low = note.lower()
    if _find_known_account(note, ctx):
        return True
    return bool(
        re.search(r"\b(via|using|through|from|into|with)\s+(?:my\s+|the\s+)?[a-z]", low)
    ) or any(
        _word_re(w).search(note)
        for w in ("cash", "upi", "gpay", "phonepe", "credit card", "debit card", "netbanking")
    )


# ------------------------------------------------------------------------------------- screens

_PERIOD_WORDS = (
    r"today|yesterday|this week|last week|this month|last month|this year|last year|"
    r"last\s+\d+\s+(?:days?|weeks?|months?)|past\s+\d+\s+(?:days?|weeks?|months?)|\d+\s*(?:d|w|m|y)\b|"
    r"(?:in\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+\d{4})?|ytd|all time|overall|so far"
)
_STAT_FILL = {"how", "much", "did", "do", "does", "have", "i", "me", "my", "we", "spend", "spent", "spending", "expense", "expenses", "earn", "earned", "save", "saved", "on", "for", "in", "the", "a", "an", "show", "give", "see", "what", "was", "were", "is", "are", "total", "report", "stats", "summary", "of", "to", "from", "during", "please", "pls", "tell", "money", "cost", "costs", "this", "last", "all", "and", "far", "so"}  # fmt: skip


def _period_args(low: str) -> str:
    m = re.search(_PERIOD_WORDS, low, re.I)
    if not m:
        return ""
    p = m.group(0).strip().lower()
    p = re.sub(r"^in\s+", "", p)
    mapping = {
        "this week": "week",
        "last week": "7d",
        "this year": "ytd",
        "last year": "1y",
        "overall": "all",
        "all time": "all",
        "so far": "mtd",
    }
    rel = re.match(r"(?:last|past)\s+(\d+)\s+(day|week|month)", p)
    if rel:
        n = int(rel.group(1)) * {"day": 1, "week": 7, "month": 30}[rel.group(2)]
        return f"{n}d"
    month = re.match(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+(\d{4}))?$", p)
    if month:
        year = int(month.group(2) or clock.today_local().year)
        num = _MONTHS[month.group(1)]
        if not month.group(2) and (year, num) > (
            clock.today_local().year,
            clock.today_local().month,
        ):
            year -= 1
        return f"{year}-{num:02d}"
    return mapping.get(p, p)


_MONTHS_WORD = re.compile(r"(\d+(?:\.\d+)?)\s*(months?|mos?|years?|yrs?|weeks?)\b", re.I)


def parse_goal(text: str) -> tuple[float, int] | None:
    """ "50000 in 6 months", "50k 6", "2 lakh in 1 year" -> (amount, months). None if unclear."""
    low = (text or "").lower()
    span = _MONTHS_WORD.search(low)
    if span:
        n = float(span.group(1))
        unit = span.group(2)[0]
        months = n * 12 if unit == "y" else n / 4.345 if unit == "w" else n
        rest = low[: span.start()] + " " + low[span.end() :]
    else:
        rest, months = low, 0.0
    amounts = [
        (m, _to_amount(m.group(1), m.group(2))) for m in _MONEY.finditer(rest) if _plausible(m)
    ]
    if not amounts:
        return None
    if not span:  # "50000 6": the small trailing number is the months
        if len(amounts) < 2 or not 0 < amounts[-1][1] <= 120:
            return None
        months = amounts[-1][1]
        amounts = amounts[:-1]
    amount = max(a for _, a in amounts)
    months = round(months)
    if amount <= 0 or not 1 <= months <= 600:
        return None
    return amount, months


@dataclass
class Fix:
    """A correction to something already recorded: change its amount, or remove it."""

    action: str  # "edit" | "delete"
    amount: float | None = None  # the right amount (edit)
    old_amount: float | None = None  # "... not 450": helps find the right entry
    keyword: str | None = None  # "the dinner": which entry; None means the last one


_AMT = r"((?:₹|rs\.?\s*|inr\s*)?\d[\d,]*(?:\.\d+)?\s*(?:k|lakhs?|lacs?|l|cr)?)"
_FIX_PREFIX = (
    r"^(?:(?:oops|oh|ops|sorry|wait|no|nope|hmm|actually|correction|my bad|whoops)[,!.]?\s+)*"
)
_NOT_KW = {"last", "previous", "prev", "that", "it", "this", "latest", "one", "entry", "expense"}


def _amt(text: str | None) -> float | None:
    if not text:
        return None
    return parse_amount(text.strip())


def parse_fix(text: str) -> Fix | None:
    """ "oops the dinner was actually 540 not 450", "change the last one to 600", "delete the coffee"."""
    low = re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip("?!. ")
    if not low or len(low) > 120:
        return None
    # "... was/is/should be 540 (not 450)"
    m = re.match(
        _FIX_PREFIX
        + r"(?:(?:the|my|that|this)\s+)?(?P<kw>[a-z][a-z &'-]{1,30}?)\s+(?:was|were|is|should\s+(?:be|have\s+been)|cost|costs|came to|came out to)\s+"
        r"(?:actually\s+|really\s+|only\s+|in fact\s+)?"
        + _AMT
        + r"(?:\s+(?:not|instead of|and not|rather than)\s+"
        + _AMT
        + ")?$",
        low,
    )
    if m:
        kw = m.group("kw").strip()
        amount = _amt(m.group(2))
        marked = (
            bool(re.match(_FIX_PREFIX, low).group(0))
            or bool(m.group(3))
            or bool(re.search(r"\b(?:actually|really|should|in fact)\b", low))
        )  # "dinner was 400" alone is a new entry; "oops, dinner was actually 400" is a correction
        if amount and marked:
            return Fix(
                "edit", amount, _amt(m.group(3)), None if kw in _NOT_KW else _tidy_keyword(kw)
            )
    # "change/edit/update/fix (the last one | the coffee) to 600", "make it 600"
    m = re.match(
        _FIX_PREFIX
        + r"(?:(?:please\s+)?(?:change|edit|update|fix|correct|set|make)\s+(?:the\s+|my\s+)?(?P<kw>[a-z][a-z &'-]{1,30}?)\s+(?:to|as|=)\s+|make\s+(?P<it>it|that)\s+)"
        + _AMT
        + r"$",
        low,
    )
    if m:
        kw = (m.group("kw") or "").strip()
        amount = _amt(m.group(3))
        if amount:
            last = (
                not kw
                or kw in _NOT_KW
                or bool(re.fullmatch(r"(?:last|previous|latest)(?: \w+)?", kw))
            )
            return Fix("edit", amount, None, None if last else _tidy_keyword(kw))
    # "delete/remove the coffee (entry)"
    m = re.match(
        r"^(?:please\s+)?(?:delete|remove|erase|scrap)\s+(?:the\s+|my\s+|that\s+)?(?P<kw>[a-z][a-z &'-]{1,30}?)(?:\s+(?:entry|expense|transaction|payment|spend|one))?$",
        low,
    )
    if m:
        kw = m.group("kw").strip()
        if kw in _NOT_KW or re.fullmatch(r"(?:last|previous|latest)(?: \w+)?", kw):
            return None  # "delete the last one" is the undo button
        return Fix("delete", keyword=_tidy_keyword(kw))
    return None


def parse_set_balance(text: str) -> tuple[str, float] | None:
    """ "bank balance is 25000", "set cash balance to 500", "I have 25000 in my bank" -> (account words, amount).

    The account words may be empty ("my balance is 25000"): the caller then uses the default account."""
    low = re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip("?!. ")
    if not low or len(low) > 100:
        return None
    pre = r"^(?:(?:ok|okay|so|btw|actually|well)[,]?\s+)?(?:please\s+)?"
    patterns = (
        pre
        + r"(?:set\s+)?(?:my\s+|the\s+)?(?P<acc>[a-z ]{0,25}?)\s*balance\s+(?:is|are|=|to|as|should be|now|now is)\s+"
        + _AMT
        + r"$",
        pre
        + r"(?:i\s+(?:currently\s+)?have|i've got|i have got|there(?:'s| is))\s+"
        + _AMT
        + r"\s+(?:left\s+)?(?:in|on)\s+(?:my\s+|the\s+)?(?P<acc>[a-z ]{2,25}?)$",
    )
    for pattern in patterns:
        m = re.match(pattern, low)
        if m:
            amount = _amt(m.group(2) if pattern is patterns[0] else m.group(1))
            if amount is None:
                continue
            return (m.group("acc") or "").strip(), amount
    return None


def _tidy_keyword(kw: str) -> str:
    return re.sub(r"\s+(?:entry|expense|transaction|payment|spend|bill)s?$", "", kw).strip()


def detect_screen(text: str) -> Screen | None:
    """Questions that should open a screen (stats, balance, history...) instead of logging."""
    t = (text or "").strip()
    low = t.lower().rstrip("?!. ")
    if not low or len(low) > 160:
        return None
    if re.search(r"\b(save|saving|savings|set aside|put aside)\b", low) and not _EXPENSE.search(
        low
    ):
        goal = parse_goal(low)
        if goal and _MONTHS_WORD.search(low):
            return Screen(
                "/plan", f"{int(goal[0]) if goal[0] == int(goal[0]) else goal[0]} {goal[1]}"
            )
    if re.fullmatch(
        r"(undo|revert|undo (?:that|it|last|the last(?: one| entry| transaction)?)|(?:delete|remove|cancel) (?:the )?last(?: one| entry| transaction)?)",
        low,
    ):
        return Screen("/undo")
    if re.search(
        r"\b(balance|how much (?:money )?do i have|net worth|my accounts?|what do i have)\b", low
    ) and not _MONEY.search(low):
        return Screen("/balance")
    if re.search(r"\b(dashboard)\b", low) and re.search(r"\b(open|show|get|link|see|my)\b", low):
        return Screen("/dashboard")
    if re.search(r"\b(export|download)\b", low) and re.search(
        r"\b(data|csv|transactions|excel|sheet|everything)\b", low
    ):
        return Screen("/export", _period_args(low))
    if re.fullmatch(
        r"(?:show |see |list |open |view )?(?:me )?(?:my |the |all )?(?:recent |last |latest )?(?:\d+ )?(?:transactions|history|entries|spends|expenses|purchases)",
        low,
    ) or re.search(
        r"\b(?:what|everything|all)\b.*\b(?:i(?:'ve| have)?|have i|did i)\s+(?:logged|entered|added|recorded|tracked|saved)\b"
        r"|\b(?:my|the)\s+(?:last|recent|latest)\s+(?:\d+\s+)?(?:transactions?|entries|spends?|expenses?|purchases?|payments?)\b"
        r"|\bwhat\s+(?:did|have)\s+i\s+(?:spend|spent|buy|bought|pay|paid)\s+(?:on\s+)?(?:recently|lately)\b",
        low,
    ):
        return Screen("/history")
    if re.fullmatch(r"(help|menu|what can you do|how (?:do|does) (?:this|it) work|commands)", low):
        return Screen("/help" if "menu" not in low else "/menu")
    if re.search(r"\bset\b.*\bbudget\b|\bbudget\b.*\b(?:to|is|of|=)\b\s*(?:₹|rs\.?\s*)?\d", low):
        mm = _MONEY.search(low)
        if mm:
            amount = _to_amount(mm.group(1), mm.group(2))
            before = low[: mm.start()] + " " + low[mm.end() :]
            name = " ".join(
                w
                for w in re.findall(r"[a-z&]+", before)
                if w
                not in {
                    "set",
                    "my",
                    "the",
                    "a",
                    "budget",
                    "for",
                    "to",
                    "of",
                    "is",
                    "at",
                    "monthly",
                    "month",
                    "per",
                    "change",
                    "update",
                    "make",
                    "rs",
                    "inr",
                }
            )
            if name:
                return Screen(
                    "/budget", f"{name} {int(amount) if amount == int(amount) else amount}"
                )
    if re.fullmatch(
        r"(?:(?:show|see|check|view|open)\s+)?(?:me\s+)?(?:my\s+|the\s+)?(?:\w+\s+)?budgets?(?:\s+(?:status|left|usage))?"
        r"|how(?:'s|\s+is|\s+are)?\s+(?:my\s+|the\s+)?(?:\w+\s+)?budgets?(?:\s+(?:going|looking|doing))?"
        r"|am i (?:over|within|on|under) (?:my )?budgets?",
        low,
    ):
        return Screen("/budget")
    if re.search(
        r"\b(?:biggest|largest|top|highest|most)\s+(?:expenses?|spend(?:ing|s)?|categor(?:y|ies))\b"
        r"|\bwhere\s+(?:does|is|did)\s+(?:all\s+)?my\s+money\s+(?:go|going|went)\b"
        r"|\bwhat\s+(?:do|did)\s+i\s+spend\s+(?:the\s+)?most\s+on\b",
        low,
    ):
        return Screen("/chart", "categories " + _period_args(low))
    if re.search(
        r"\bhow much\s+(?:money\s+|cash\s+)?(?:do i have\s+|is\s+|have i\s+(?:got\s+)?|left\s+)?(?:in|left in|is in)\s+(?:my\s+)?(?:bank|cash|wallet|upi|savings|credit card|account)\b",
        low,
    ):
        return Screen("/balance")
    asks_total = re.search(
        r"\b(how much|total|what(?:'s| is| was| did| were)|show|give|see|tell)\b.*\b(spend|spent|spending|expenses?|earn(?:ed)?|income|saved?|cost|report|stats|summary|breakdown)\b",
        low,
    ) or re.fullmatch(r"(?:my )?(?:spending|expenses|stats|report|summary|breakdown)(?: .*)?", low)
    if not asks_total and re.fullmatch(
        r"(?:(?:i\s+)?(?:spent|spend|spending|expenses?)\s+(?:on\s+)?)(?P<what>[a-z&\s]{2,30}?)\s+(?P<per>today|this week|this month|last week|last month|this year|yesterday)",
        low,
    ):
        asks_total = True  # "spent on food this week"
    if asks_total and not (_EXPENSE.search(low) and _MONEY.search(low)):
        period = _period_args(low)
        rest = re.sub(_PERIOD_WORDS, " ", low, flags=re.I)
        words = [w for w in re.findall(r"[a-z&]+", rest) if w not in _STAT_FILL]
        return Screen("/stats", " ".join(filter(None, [period, " ".join(words[:3])])).strip())
    return None
