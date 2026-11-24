"""
ai_extractor.py — Transaction extraction and clarification
------------------------------------------------------
Detects both DEBIT (expenses) and CREDIT (income) from natural language.
"""

import os
import json
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from debt_language import completed_repayment, PROMISE_RETURN, debt_intent, loan_intent, named_return
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

try:
    from groq import APIError, Groq
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False


EXPENSE_CATEGORIES = [
    "Food & Dining", "Groceries", "Transport", "Health & Medical",
    "Entertainment", "Shopping", "Utilities & Bills", "Education",
    "Travel", "Personal Care", "Home & Maintenance", "Subscriptions", "Other",
]

INCOME_CATEGORIES = [
    "Salary", "Freelance", "Gift", "Reimbursement",
    "Investment Returns", "Rental Income", "Other Income",
]

ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES

DEBIT_HINTS = {
    "Food & Dining": ["food", "lunch", "dinner", "breakfast", "snack", "meal", "restaurant", "cafe", "coffee", "chai", "tea", "ice cream", "khana"],
    "Groceries": ["grocery", "groceries", "supermarket", "vegetable", "milk", "rice"],
    "Transport": ["uber", "ola", "taxi", "cab", "petrol", "fuel", "bus", "train", "metro", "auto", "fare", "transport", "transportation"],
    "Health & Medical": ["doctor", "hospital", "medicine", "pharmacy", "dental", "dentist"],
    "Entertainment": ["movie", "cinema", "game", "concert"],
    "Shopping": ["shopping", "clothes", "amazon", "flipkart", "mall"],
    "Utilities & Bills": ["electricity", "water", "internet", "wifi", "recharge", "phone bill"],
    "Education": ["course", "tuition", "school", "college", "book", "exam"],
    "Travel": ["trip", "flight", "hotel", "travel", "vacation"],
    "Personal Care": ["salon", "barber", "haircut", "spa", "grooming"],
    "Home & Maintenance": ["rent", "kiraya", "kiraaya", "kiraye", "repair", "plumber", "maintenance", "furniture", "home"],
    "Subscriptions": ["subscription", "prime", "netflix", "spotify", "youtube premium"],
}

INCOME_HINTS = {
    "Salary": ["salary", "paycheck", "stipend"],
    "Freelance": ["freelance", "client", "project payment"],
    "Gift": ["gift", "present"],
    "Reimbursement": ["refund", "refunded", "reimburse", "reimbursement", "got back", "wapas", "waapas"],
    "Investment Returns": ["interest", "dividend", "returns", "profit"],
    "Rental Income": ["rent", "tenant", "kiraya", "kiraaya"],
    "Other Income": ["received", "got", "income", "credit"],
}

MERCHANT_NORMALIZATION = {
    "uber": "Uber",
    "ola": "Ola",
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "netflix": "Netflix",
    "spotify": "Spotify",
}

FUTURE_CONFIRM_PHRASES = (
    "confirm future date",
    "allow future date",
    "approved future date",
    "future date confirmed",
    "yes future date",
    "use future date",
)


def _compute_confidence(txn: dict):
    score = 0.9
    uncertain = []

    if not txn.get("amount") or float(txn.get("amount", 0)) <= 0:
        score -= 0.5
        uncertain.append("amount")

    note = str(txn.get("note", "")).strip().lower()
    if note in ("", "transaction"):
        score -= 0.2
        uncertain.append("note")

    if txn.get("transaction_type") == "credit":
        if txn.get("category") == "Other Income":
            score -= 0.2
            uncertain.append("category")
    else:
        if txn.get("category") == "Other":
            score -= 0.2
            uncertain.append("category")

    if txn.get("date") == str(date.today()):
        score -= 0.1
        uncertain.append("date")

    score = max(0.05, min(0.99, round(score, 2)))
    if score >= 0.75:
        label = "high"
    elif score >= 0.45:
        label = "medium"
    else:
        label = "low"

    return label, score, sorted(set(uncertain))


def _normalize_merchant_text(text: str) -> str:
    normalized = text
    for variant, canonical in MERCHANT_NORMALIZATION.items():
        normalized = re.sub(rf"\b{re.escape(variant)}\b", canonical, normalized, flags=re.IGNORECASE)
    return normalized


def _pick_category(text: str, txn_type: str) -> str:
    if txn_type == "credit" and re.search(r"\bgot\s+(?:₹\s*)?\d[\d,.]*\s+back\b", text, re.I):
        return "Reimbursement"
    hints = INCOME_HINTS if txn_type == "credit" else DEBIT_HINTS
    for category, words in hints.items():
        if any(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) for word in words):
            return category
    return "Other Income" if txn_type == "credit" else "Other"


def _cleanup_note(note: str) -> str:
    cleaned = re.sub(r"\b(and|then|also|for|to|on|at|in)\b", " ", note, flags=re.IGNORECASE)
    cleaned = "".join(char if char.isalnum() or unicodedata.category(char).startswith("M") else " " for char in cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _normalize_merchant_text(cleaned)
    return cleaned[:50]


def _prepare_transaction(txn: dict, user_message: str) -> dict:
    prepared = dict(txn)
    prepared["transaction_type"] = "credit" if prepared.get("transaction_type") == "credit" else "debit"
    prepared["amount"] = float(prepared["amount"])
    prepared["category"] = prepared.get("category", "Other")
    prepared["date"] = txn["date"].isoformat()
    prepared["note"] = _normalize_merchant_text(str(prepared.get("note", "")))
    if not prepared["note"]:
        prepared["note"] = "transaction"

    merchant_match = re.search(
        r"\b(uber|ola|swiggy|zomato|amazon|flipkart|netflix|spotify)\b",
        prepared["note"],
        flags=re.IGNORECASE,
    )
    if merchant_match:
        prepared["merchant"] = MERCHANT_NORMALIZATION[merchant_match.group(1).lower()]

    if prepared["transaction_type"] == "credit":
        if prepared["category"] not in INCOME_CATEGORIES:
            prepared["category"] = "Other Income"
    else:
        if prepared["category"] not in EXPENSE_CATEGORIES:
            prepared["category"] = "Other"

    label, score, uncertain = _compute_confidence(prepared)
    prepared["confidence_label"] = label
    prepared["confidence_score"] = score
    prepared["uncertain_fields"] = uncertain
    prepared["raw_input"] = user_message
    return prepared


MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
MONTH_NUMBERS = {name: i for i, name in enumerate(MONTHS, 1)}
MONTH_NUMBERS.update({name[:3]: i for i, name in enumerate(MONTHS, 1)})
MONTH_PATTERN = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DATE_PATTERN = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH_PATTERN})(?:\s+\d{{4}})?"
    rf"|(?:{MONTH_PATTERN})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"
    rf"|\d+\s+days?\s+ago|(?:last|this)\s+(?:{'|'.join(WEEKDAYS)})"
    r"|today|yesterday|yday|tomorrow|now|aaj|kal)\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?<![\w./])(?P<sign>[-+])?\s*(?:₹\s*|(?:rs\.?|inr)\s*)?"
    r"(?P<number>\d+(?:,\d+)*(?:\.\d+)?|\.\d+)"
    r"(?:\s*(?P<scale>k|thousand|lakhs?|lacs?|crores?))?(?![\w/]|\.\d)",
    re.IGNORECASE,
)
AMOUNT_SCALES = {
    "k": 1_000, "thousand": 1_000, "lakh": 100_000, "lac": 100_000, "crore": 10_000_000,
}
COUNT_PATTERN = re.compile(
    r"(?<![\d₹.,])\b\d+\s+(?:(?:train|bus|movie|flight)\s+)?"
    r"(?:tickets?|people|persons?|items?|units?|kg|kilograms?|litres?|liters?)\b",
    re.IGNORECASE,
)
CONFIRMATION = re.compile(
    r"(?:^\s*|[;,]\s*|\s+)(?:" + "|".join(FUTURE_CONFIRM_PHRASES) + r")\s*[.!]?\s*$",
    re.IGNORECASE,
)
NO_PAYMENT = re.compile(
    r"\b(?:did not pay|didn['’]t pay|haven['’]t paid|have not paid|never paid|not paid|"
    r"not returned|never returned|not repaid|never repaid|did not return|did not repay|"
    r"did not lend|didn['’]t lend|haven['’]t lent|have not lent|never lent|not lent|"
    r"(?:will|might|would|need to|going to) lend|planning to lend|"
    r"(?:card|payment|transaction) (?:was )?(?:declined|failed)|(?:payment|transaction) (?:is )?pending|"
    r"(?:will|might|would|need to|going to) pay|remind me|planning to)\b",
    re.IGNORECASE,
)
CREDIT = re.compile(
    r"\b(?:received|got|earned|credited|credit|income|salary|stipend|paycheck|came in|"
    r"mila|mili|mile|(?:wapas|waapas) (?:diye|diya)|refunded|refund kiya|refund\b.*\b(?:arrived|came))\b",
    re.IGNORECASE,
)
DEBIT = re.compile(
    r"\b(?:paid|spent|bought|gave|lent|loaned|purchased|pay|cost|diye|diya|bhara|chukaya|laya|laaya|kharida|ate food|khana khaya|credit card|"
    r"(?:i|we) refunded|(?:maine|humne) refund kiya)\b",
    re.IGNORECASE,
)
SPLIT = re.compile(r"\b(?:split|my share|share of|total (?:was|of|bill)|(?:bill|dinner) total|owes? me)\b", re.IGNORECASE)
HALF_SPLIT = re.compile(
    r"\b(?:split (?:it )?(?:(?:in|into|between) (?:half|two|2)|50/50)|half each)\b", re.IGNORECASE,
)
OWES_ME = re.compile(r"(?P<person>[^\s,.;!?]+)\s+(?:still\s+)?owes? me\b", re.IGNORECASE)
UPCOMING_REPAYMENT = re.compile(
    r"\b(?:(?:i(?:['’]ll| will)|i (?:should|expect to)|(?:i |and |so )(?:have to|need to))"
    r"\s+(?:get|take|receive)\b[^.;!?]*?\bback\b|"
    r"will pay me back|will send me back)\b|आएंगे|आएँगे|आएगा", re.IGNORECASE,
)
STANDALONE_DEBT = re.compile(
    r"^(?:remind me(?: that)?\s+)?(?:i (?:still )?owe (?P<to>[^\d₹,.;!?]+?)|(?P<from>[^\d₹,.;!?]+?)\s+owes? me)"
    r"(?:\s+(?=(?:₹\s*)?\d)|(?=[.!?]*$))",
    re.IGNORECASE,
)
TO_GIVE = re.compile(
    r"\b(?:(?:i|we) (?:have|need) to (?:give|pay)|(?:it|that) (?:is|was) to give|still to (?:give|pay))\b",
    re.IGNORECASE,
)
FROM_THAT = re.compile(r"\b(?:from that|out of that|usme se|usmein se)\b", re.IGNORECASE)
BALANCE_PREFIX = re.compile(
    r"\b(?:(?:from|out of) (?:the )?(?:remaining(?: balance(?: of)?)?|balance of)\s+"
    r"(?:₹\s*)?\d+(?:,\d+)*(?:\.\d+)?(?:\s+rupees?)?\b"
    r"|(?:from|out of) (?:what was left|the rest|the remaining balance)\b"
    r"|(?:baaki|baki|bache hue|बचे हुए)\s+(?:(?:ke|के)\s+)?"
    r"(?:(?:₹\s*)?\d+(?:,\d+)*(?:\.\d+)?(?:\s+rupees?)?\s+)?"
    r"(?:mein se|me se|में से|मे से))\s*[,;:]?",
    re.IGNORECASE,
)
SAVINGS_SUFFIX = re.compile(
    r"(?<=[,.!?])\s*(?=(?:baaki|baki|(?:i\s+)?saved|(?:i\s+)?set aside)\b[^,.;!?]*"
    r"\b(?:set aside|saved|save kar(?: li(?:ya)?|[aei]?))\b)"
    r"|(?<=[,.!?])\s*(?=(?:i\s+)?(?:saved|set aside)\b)",
    re.IGNORECASE,
)
OWN_PAYMENT = re.compile(r"\b(?:(?:i|we) paid|maine|humne|i covered)\b", re.IGNORECASE)
OWN_SHARE = re.compile(r"\bmy share\b", re.IGNORECASE)
EXPLICIT_PAYMENT = re.compile(r"\b(?:i|we)\s+(?:paid|covered|spent)\b", re.I)
ALTERNATIVES = re.compile(r"\b(?:or|ya)\b", re.IGNORECASE)
CORRECTION = re.compile(
    r"(?:(?<=[.!?,;])\s*|\s+)\b(?:no|nahi|nahin|sorry|actually|i mean|mera matlab|rather)\b"
    r"(?:[\s,.!;:–—-]+(?:no|nahi|nahin)\b)*[\s,.!;:–—-]*",
    re.IGNORECASE,
)
RENT = re.compile(r"\b(?:rent|kiraya|kiraaya|kiraye)\b", re.IGNORECASE)
SET_ASIDE = re.compile(
    r"\b(?:set aside|kept aside|put aside|saved|saving|save kar(?: li(?:ya)?|[aei]?)|"
    r"bachaya|bachaaye|alag rakh[aei])\b", re.IGNORECASE,
)
FOREIGN_CURRENCY = re.compile(r"[$€£¥]|\b(?:USD|EUR|GBP|JPY|CAD|AUD|dollars?|euros?)\b", re.IGNORECASE)
OTHER_PAYER = re.compile(
    r"^my (?:friend|partner|brother|sister|mother|father)\s+(?:paid|bought|spent)\b",
    re.IGNORECASE,
)
WRITTEN_NUMBER = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakhs?|crores?)\b",
    re.IGNORECASE,
)


class ClarificationNeeded(ValueError):
    def __init__(self, kind, question, *, date_to_confirm=None, amount=None, suggestion=None):
        super().__init__(question)
        self.kind = kind
        self.date_to_confirm = date_to_confirm
        self.amount = amount
        self.suggestion = suggestion


def _resolve_date(text: str, today: date) -> date:
    text = text.lower().strip()
    if text in {"today", "now", "aaj"}:
        return today
    if text in {"yesterday", "yday", "tomorrow"}:
        return today + timedelta(days=1 if text == "tomorrow" else -1)
    if text.startswith(("last ", "this ")):
        when, weekday = text.split(maxsplit=1)
        days = (today.weekday() - WEEKDAYS.index(weekday)) % 7
        return today - timedelta(days=days or (7 if when == "last" else 0))
    if text.endswith("ago"):
        return today - timedelta(days=int(text.split()[0]))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)

    parts = re.findall(r"\d+|[a-z]+", re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", text))
    first, second, *year = parts
    year_value = int(year[0]) if year else today.year
    if year and len(year[0]) == 2:
        year_value += 2000
    if first in MONTH_NUMBERS:
        return date(year_value, MONTH_NUMBERS[first], int(second))
    if second in MONTH_NUMBERS:
        return date(year_value, MONTH_NUMBERS[second], int(first))
    day, month = int(first), int(second)
    if 1 <= day <= 12 and 1 <= month <= 12 and day != month:
        raise ClarificationNeeded("date", f"Which date did you mean by {text}? Reply in YYYY-MM-DD format.")
    if month > 12:
        day, month = month, day
    return date(year_value, month, day)


def _amount_candidates(clause):
    # Preserve offsets so corrections can replace the amount in the original text.
    without_dates = DATE_PATTERN.sub(lambda m: " " * len(m[0]), clause)
    without_counts = COUNT_PATTERN.sub(lambda m: " " * len(m[0]), without_dates)
    without_counts = HALF_SPLIT.sub(lambda m: " " * len(m[0]), without_counts)
    return list(AMOUNT_PATTERN.finditer(without_counts))


def _apply_amount_corrections(clause):
    while True:
        markers = list(CORRECTION.finditer(clause))
        if not markers:
            break
        marker = markers[0]
        end = markers[1].start() if len(markers) > 1 else len(clause)
        before, after = clause[:marker.start()], clause[marker.end():end]
        old, new = _amount_candidates(before), _amount_candidates(after)
        if len(old) != 1 or len(new) != 1:
            break
        replacement = new[0]
        lead = after[:replacement.start("number")].strip(" ₹+-").lower()
        if lead not in {"", "rs", "rs.", "inr", "it was", "it is", "woh", "wo"}:
            break
        tail = after[replacement.end():].strip(" .,;")
        # A trailing date or payee can supply context, but don't silently replace a second payment.
        if (CREDIT.search(tail) or DEBIT.search(tail)) and re.search(r"\w", before[:old[0].start()] + before[old[0].end():]):
            break
        original = old[0]
        value = replacement[0].strip()
        clause = f"{before[:original.start()]} {value} {before[original.end():]} {tail} {clause[end:]}".strip()
    return clause


def _amount(match):
    number = match["number"]
    if "," in number and not re.fullmatch(
        r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?", number
    ):
        raise ValueError("Enter an amount with valid digit grouping, such as 1,250.50.")
    multiplier = AMOUNT_SCALES.get((match["scale"] or "").lower().rstrip("s"), 1)
    return _validate_amount(Decimal(f"{match['sign'] or ''}{number.replace(',', '')}") * multiplier)


def _validate_amount(amount):
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1000000000000"):
        raise ValueError("Enter a positive amount below ₹1 trillion.")
    if amount % Decimal("0.01"):
        raise ValueError("Enter an amount with at most two decimal places.")
    return amount


def _clauses(message):
    # A pause between the verb and amount is common in dictated lists.
    message = re.sub(r"\b(paid|spent|received)\.\s+(?=₹?\s*\d)", r"\1 ", message, flags=re.I)
    message = re.sub(r"\b(?:splited|splitted)\b", "split", message, flags=re.I)
    message = re.sub(r"\b(no|nahi|nahin)[,.;]\s*(?=(?:no|nahi|nahin)\b|₹?\s*\d)", r"\1 ", message, flags=re.I)
    # Recognizers often put the comma after a trailing verb in a mixed-language list.
    message = re.sub(
        r"\b(mila|mili|mile|diya|diye|bhara|laya|laaya|kharida)[,.;]?\s+(?=(?:from that|out of that|usme se|usmein se)\b|₹?\s*\d)",
        r"\1; ", message, flags=re.I,
    )
    # A stated balance describes the source of the next expense, not its amount.
    message = re.sub(r"\s+(?:out of that|from that)\s+(?=(?:i|we)\s+(?:gave|spent|paid|bought)\b)", "; ", message, flags=re.I)
    message = re.sub(r",?\s+but\s+(?=(?:i\s+)?(?:paid|spent|received|did not pay)\b)", "; ", message, flags=re.I)
    message = BALANCE_PREFIX.sub("; ", message)
    message = SAVINGS_SUFFIX.sub("; ", message)
    parts = re.split(
        r"\s*[;\n]\s*|(?<=[.!?])\s+(?=(?:i\s+)?(?:paid|spent|received|got|earned|bought|gave|maine|humne|aaj|kal)\b|₹?\s*\d)"
        r"|(?<=[.!?,])\s+(?=i (?:owe|still owe|(?:have to|need to|will) (?:give|pay|return|repay))\b)"
        r"|\s+(?:and then|and also|and|then|aur)[.,]?\s+"
        r"|,\s+(?=(?:i\s+)?(?:paid|spent|received|got|earned)\b|₹?\s*\d)",
        message, flags=re.IGNORECASE,
    )
    clauses = []
    for part in filter(None, (part.strip() for part in parts)):
        part = re.sub(r"^(?:(?:and|aur)\b[.,]?\s*)+", "", part, flags=re.I)
        part = FROM_THAT.sub("", part, count=1).strip() if FROM_THAT.match(part) else part
        if not part:
            continue
        if clauses and DEBIT.search(clauses[-1]) and re.match(r"^(?:₹\s*)?\d[\d,.]*\s+on\s+\w", part, re.I):
            part = "spent " + part
        if clauses and (
            CORRECTION.match(" " + part)
            or re.match(r"(?:friends\b.*\bowe|split\b|shared\b|confirm future date\b)", part, re.I)
            or (HALF_SPLIT.search(part) and not DEBIT.search(part))
            or (SPLIT.search(clauses[-1]) and OWN_PAYMENT.match(part))
            or ((SPLIT.search(clauses[-1]) or DEBIT.search(clauses[-1]))
                and not EXPLICIT_PAYMENT.match(part)
                and (OWES_ME.search(part) or UPCOMING_REPAYMENT.search(part) or named_return(part)
                     or (loan_intent(clauses[-1]) and PROMISE_RETURN.search(part))))
            or (not _amount_candidates(clauses[-1]) and not DEBIT.search(clauses[-1])
                and not CREDIT.search(clauses[-1]) and not NO_PAYMENT.search(clauses[-1]))
            or (not _amount_candidates(part) and not DEBIT.search(part) and not CREDIT.search(part)
                and not NO_PAYMENT.search(part) and not SET_ASIDE.search(part))
        ):
            clauses[-1] += " " + part
        else:
            clauses.append(part)
    isolated = []
    for clause in clauses:
        # A completed receipt followed by amounts and an outgoing verb is two events.
        split = re.search(
            r"\b(?:mila|mili|mile|credited)\b\s*[,.:]?\s+(?=₹?\s*\d)", clause, re.I,
        )
        if split and DEBIT.search(clause, split.end()) and _amount_candidates(clause[:split.end()]):
            isolated.extend((clause[:split.end()].strip(), clause[split.end():]))
        else:
            isolated.append(clause)
    return [_apply_amount_corrections(clause) for clause in isolated]


def _direction(clause):
    debit = DEBIT.search(clause)
    credit = CREDIT.search(clause)
    if re.search(r"\b(?:i|we) refunded\b|\b(?:maine|humne) refund kiya\b", clause, re.I):
        return "debit"
    if re.search(r"\b(?:refund\b.*\b(?:arrived|came)|refund kiya)\b", clause, re.I):
        return "credit"
    if re.search(r"\b(?:wapas|waapas) (?:diye|diya)\b", clause, re.I):
        return "credit"
    if RENT.search(clause):
        # A bill is outgoing by default. Explicitly receiving rent is rental income.
        return "credit" if credit and not debit else "debit"
    if credit and re.search(r"\b(?:mila|mili|mile)\s*[,.!]*$", clause, re.I):
        return "credit"
    if credit and (not debit or credit.start() < debit.start()):
        return "credit"
    return "debit"


def _written_amount(clause):
    # Groq can translate a written amount. Direction, dates, and save decisions stay local.
    if not WRITTEN_NUMBER.search(clause):
        return None
    try:
        api_key = os.environ.get("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY")
    except StreamlitSecretNotFoundError:
        return None
    if not api_key or not _GROQ_AVAILABLE:
        return None
    try:
        result = Groq(api_key=api_key, timeout=5.0, max_retries=0).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": 'Extract only the amount actually paid or received, in INR. Return JSON with one key "amount". Use null when unclear or missing.'},
                {"role": "user", "content": clause},
            ],
            temperature=0,
            max_tokens=30,
            response_format={"type": "json_object"},
        )
        value = json.loads(result.choices[0].message.content)["amount"]
        return _validate_amount(Decimal(str(value)))
    except (APIError, InvalidOperation, AttributeError, ValueError, KeyError, IndexError, TypeError):
        return None


def _rupees(amount):
    return f"₹{amount:,.2f}".removesuffix(".00")


def _transaction_subject(clause, direction):
    if RENT.search(clause):
        return "rent"
    if re.search(r"\b(?:movie|cinema)\b", clause, re.I):
        return "the movie"
    if re.search(r"\bfare\b", clause, re.I):
        return "the fare"
    meal = re.search(r"\b(?:lunch|dinner|breakfast)\b", clause, re.I)
    if meal:
        return meal[0].lower()
    category = _pick_category(clause, direction)
    if category not in {"Other", "Other Income"}:
        return category.lower()
    return "the money received" if direction == "credit" else "this expense"


def _repayment_parts(clause):
    owed = OWES_ME.search(clause)
    upcoming = UPCOMING_REPAYMENT.search(clause)
    promised = PROMISE_RETURN.search(clause)
    named = named_return(clause)
    start = min((match.start() for match in (owed, upcoming, promised, named) if match), default=len(clause))
    payment, repayment = clause[:start], clause[start:]
    source = re.search(r"\bback\s+from\s+(?P<person>[^\s,.;!?]+)", repayment, re.I)
    counterparty = source or owed or named
    person = counterparty["person"] if counterparty else ""
    if person.lower() in {"friend", "they", "he", "she", "you", "me", "someone", "still", "जिसमें", "जिसमे"}:
        person = ""
    return payment, repayment, person


def _repayment_name(person):
    return person[:1].upper() + person[1:]


def _reminder_amount(text):
    matches = _amount_candidates(text)
    if not matches or ALTERNATIVES.search(text) or FOREIGN_CURRENCY.search(text):
        return None
    try:
        amounts = {_amount(match) for match in matches}
        return amounts.pop() if len(amounts) == 1 else None
    except ValueError:
        return None


def _extract_reminder(clause, answers, today):
    intent = debt_intent(clause)
    if not intent:
        return None
    prefix = clause[:intent["start"]]
    if _amount_candidates(prefix) and (
        DEBIT.search(prefix) or CREDIT.search(prefix) or _pick_category(prefix, "debit") != "Other"
    ):
        return None  # A paid bill followed by its repayment is handled as a split.
    direction = answers.get("debt_direction") or intent["direction"]
    person = answers.get("person") or intent["person"]
    amount = answers.get("amount") or _reminder_amount(clause)
    tail = clause
    if direction == "ambiguous":
        what = f"₹{amount:,.2f}".removesuffix(".00") if amount else "this amount"
        raise ClarificationNeeded(
            "direction", f"For {what}, do you need to pay someone, or collect the money from them?",
            amount=amount,
        )
    if amount is None:
        question = f"How much do you owe {person}?" if direction == "pay" and person else "How much do you still need to pay?"
        if direction == "collect":
            question = f"How much does {person or 'the other person'} owe you?"
        raise ClarificationNeeded("amount", question)
    if not person:
        question = f"Who do you still owe {_rupees(amount)} to?" if direction == "pay" else f"Who owes you {_rupees(amount)}?"
        raise ClarificationNeeded("person", question, amount=amount)
    date_match = DATE_PATTERN.search(tail)
    date_text = answers.get("date") or (date_match[0] if date_match else "")
    try:
        due_date = _resolve_date("tomorrow" if date_text.lower() == "kal" else date_text, today).isoformat() if date_text else None
    except (ValueError, OverflowError):
        raise ClarificationNeeded("date", f"When is {_rupees(amount)} due? Give the date, such as 20 November.") from None
    return {
        "direction": direction, "person": _repayment_name(person), "amount": float(amount), "due_date": due_date,
        "note": "",
    }


def _extract_clause(clause, answers, future_confirmed, today, *, allow_remote_amount):
    if SET_ASIDE.search(clause) and not CREDIT.search(clause) and not DEBIT.search(clause):
        return None
    if answers.get("refund") is False:
        return None
    half_split = HALF_SPLIT.search(clause)
    loan = loan_intent(clause)
    payment_text, repayment_text, person = _repayment_parts(clause)
    if repayment_text and not _amount_candidates(payment_text) and not DEBIT.search(payment_text):
        raise ClarificationNeeded("details", "What did you pay for, and how much did you pay upfront?")
    settlement = completed_repayment(payment_text)
    direction = settlement[0] if settlement else _direction(payment_text)
    refund = re.search(r"\b(?:refund(?:ed)?|reimbursement)\b", clause, re.I)
    if refund and not answers.get("refund"):
        settled = re.search(
            r"\b(?:received|got|arrived|came|credited|refunded|refund kiya|wapas)\b", clause, re.I
        )
        pending = re.search(r"\b(?:pending|requested|waiting|expected|will|might|should|not received)\b", clause, re.I)
        if not settled or pending:
            raise ClarificationNeeded("refund", "Has the refund already arrived? Reply yes or no.")
    if answers.get("refund"):
        direction = "credit"
    if direction == "debit" and OTHER_PAYER.search(clause) and "payer" not in answers:
        raise ClarificationNeeded("payer", "Did this payment come out of your money? Reply yes or no.")
    if answers.get("payer") is False:
        return None
    subject = _transaction_subject(clause, direction)

    date_matches = list(DATE_PATTERN.finditer(HALF_SPLIT.sub(" ", payment_text)))
    date_text = answers.get("date") or (date_matches[0][0] if date_matches else "")
    if date_text.lower() == "kal":
        if DEBIT.search(clause) or CREDIT.search(clause):
            date_text = "yesterday"
        else:
            raise ClarificationNeeded("date", "Which date did you mean by kal? Reply in YYYY-MM-DD format.")
    if len(date_matches) > 1 and not answers.get("date"):
        raise ClarificationNeeded("date", "Which date was this transaction on? Reply in YYYY-MM-DD format.")
    try:
        txn_date = _resolve_date(date_text, today) if date_text else today
    except ClarificationNeeded:
        raise
    except (ValueError, OverflowError):
        raise ClarificationNeeded("date", "That date is invalid. What was the date in YYYY-MM-DD format?") from None
    if txn_date > today and not (future_confirmed or answers.get("future") == txn_date):
        raise ClarificationNeeded(
            "future", f"Save this transaction for {txn_date.isoformat()}? Reply yes or give the correct date.",
            date_to_confirm=txn_date,
        )

    amount = answers.get("amount")
    if re.search(r"\bsalary\b", payment_text, re.I) and re.search(r"\bdeducted\b", payment_text, re.I) and len(_amount_candidates(payment_text)) == 2:
        if amount is None:
            raise ClarificationNeeded("net_salary", "After the deduction, how much salary actually reached your account?")
        # The credited amount already accounts for withholding.
        direction = "credit"
    if amount is None:
        amount_source = payment_text
        if (SPLIT.search(clause) or repayment_text) and not loan:
            own = OWN_PAYMENT.search(clause)
            share = OWN_SHARE.search(clause)
            share_suffix = payment_text[share.end():] if share else ""
            if _amount_candidates(share_suffix):
                amount_source = share_suffix
            elif ((repayment_text or half_split) and EXPLICIT_PAYMENT.search(payment_text)
                  and len(_amount_candidates(payment_text)) == 1):
                amount_source = payment_text
            elif own and (
                re.search(r"\b(?:only|i covered|entire|full|baaki)\b", clause, re.I)
                or re.search(r"\btotal\b", clause[:own.start()], re.I)
            ):
                amount_source = re.split(
                    r";|\b(?:friends\b.*?\bowe|baaki)\b", payment_text[own.end():], maxsplit=1, flags=re.I,
                )[0]
            elif share and len(_amount_candidates(clause)) == 1:
                amount_source = payment_text
            else:
                split_amounts = _amount_candidates(payment_text)
                total_hint = ""
                total = None
                if len(split_amounts) == 1:
                    try:
                        total = _amount(split_amounts[0])
                        total_hint = f"I heard {_rupees(total)} for {subject}. "
                    except ValueError:
                        pass
                stated_due = _reminder_amount(repayment_text)
                if total and stated_due:
                    who = f" from {person}" if person else ""
                    question = f"Did you pay {_rupees(total)} for {subject}? I’ll track {_rupees(stated_due)} to collect{who}."
                    if not person:
                        question += " You can include who owes you in your reply."
                else:
                    question = f"{total_hint}How much did you personally pay for {subject}?"
                raise ClarificationNeeded(
                    "amount",
                    question,
                    suggestion=total,
                )
        if refund:
            amount_source = re.split(r"\b(?:of my original|from (?:the |an? )?original)\b", amount_source, maxsplit=1, flags=re.I)[0]
        matches = _amount_candidates(amount_source)
        try:
            amount = _reminder_amount(amount_source) if loan else _amount(matches[0]) if len(matches) == 1 else None
            if not matches and allow_remote_amount:
                amount = _written_amount(amount_source)
        except (ValueError, InvalidOperation) as exc:
            raise ClarificationNeeded("amount", str(exc)) from None
        if amount is None or ALTERNATIVES.search(amount_source) or FOREIGN_CURRENCY.search(amount_source):
            question = f"How much was it for {subject}? Say the amount in rupees."
            if len(matches) > 1:
                options = " or ".join(dict.fromkeys("₹" + match["number"] + (f" {match['scale']}" if match["scale"] else "") for match in matches))
                question = f"For {subject}, did you mean {options}? Say the correct amount in rupees."
            if FOREIGN_CURRENCY.search(amount_source):
                question = f"What amount in rupees should I record for {subject}?"
            raise ClarificationNeeded("amount", question)
    category = _pick_category(payment_text, direction)
    if settlement:
        category = "Reimbursement" if direction == "credit" else "Other"
    if not settlement and category == "Other" and not answers.get("details") and not (DEBIT.search(clause) or CREDIT.search(clause)):
        raise ClarificationNeeded(
            "details",
            f"What was {_rupees(amount)} for? Say what you paid for, or tell me if you received the money.",
            amount=amount,
        )
    note = _cleanup_note(AMOUNT_PATTERN.sub(" ", DATE_PATTERN.sub(" ", clause)))
    labels = {"mile": "Money received", "mili": "Money received", "mila": "Money received", "rent था": "Rent",
              "a friend diye": "Gave to a friend", "a friend diya": "Gave to a friend",
              "dost ko diye": "Gave to a friend", "dost ko diya": "Gave to a friend",
              "का ate food": "Food", "ki khana khaya": "Food", "ka khana khaya": "Food",
              "का transportation में cost": "Transportation",
              "fare cost": "Fare", "transport cost": "Transport"}
    note = labels.get(note.lower(), note)
    repayment = None
    if (repayment_text or half_split or loan or answers.get("due")) and direction == "debit":
        split_person = re.search(r"\bwith\s+(?P<person>[^\s,.;!?]+)", clause[half_split.end():], re.I) if half_split else None
        person = (answers.get("repayment_person") or answers.get("person") or person
                  or (loan["person"] if loan else "") or (split_person["person"] if split_person else ""))
        label = subject.removeprefix("the ").capitalize()
        due = answers.get("due")
        if "due" not in answers:
            due = _reminder_amount(repayment_text)
            if loan and not repayment_text:
                due = amount
        if loan and not person:
            raise ClarificationNeeded("person", f"Who did you lend {_rupees(amount)} to?", amount=amount)
        if "due" not in answers and not (due and due <= amount):
            half = None
            totals = _amount_candidates(payment_text)
            if half_split and len(totals) == 1:
                try:
                    half = _validate_amount(_amount(totals[0]) / 2)
                    if half > amount:
                        half = None
                except ValueError:
                    pass
            who = f"does {person} still owe you" if person else "are you expecting back"
            suggestion = f" Half is {_rupees(half)}." if half else ""
            raise ClarificationNeeded(
                "due", f"How much {who} for {subject}?{suggestion} "
                "Say the amount to track it, or say “skip repayment”.",
                amount=amount, suggestion=half,
            )
        if due:
            repayment = {"amount": float(due), "person": _repayment_name(person)}
        note = label
        if loan:
            note = f"Loan to {person}"
    elif SPLIT.search(clause) and subject == "the movie":
        note = "Movie"
    transaction = {
        "amount": amount, "transaction_type": direction, "date": txn_date,
        "category": category, "note": note,
    }
    if settlement:
        transaction["settlement_person"] = settlement[1]
        preposition = "from" if direction == "credit" else "to"
        transaction["note"] = f"Repayment {preposition} {settlement[1]}"
    if repayment:
        transaction["repayment"] = repayment
    return transaction


def _extract_context(context):
    raw_input = context["raw_input"]
    today = context["today"]
    transactions = []
    reminders = []
    pending = None
    event_date = None
    for index, clause in enumerate(context["clauses"]):
        answers = context["answers"].get(index, {})
        if answers.get("details"):
            original_intent = debt_intent(clause)
            clause = answers["details"]
            if original_intent and original_intent["person"] and not answers.get("person"):
                answers = {**answers, "person": original_intent["person"]}
        try:
            reminder = _extract_reminder(clause, answers, today)
            if reminder:
                reminder["parsed_phrase"] = clause
                reminders.append(reminder)
                continue
            if NO_PAYMENT.search(clause):
                # A declined card can qualify the preceding payment without repeating its amount.
                if index and not _amount_candidates(clause) and re.search(r"declined|failed", clause, re.I):
                    previous = context["clauses"][index - 1]
                    if transactions and transactions[-1].get("parsed_phrase") == previous:
                        transactions.pop()
                continue
            payment_text = _repayment_parts(clause)[0]
            if event_date and not answers.get("date") and not DATE_PATTERN.search(payment_text):
                answers = {**answers, "date": event_date}
            txn = _extract_clause(clause, answers, context["future_confirmed"], today,
                                  allow_remote_amount=context.get("allow_remote_amount", True))
        except ClarificationNeeded as exc:
            if pending is None:
                pending = {
                    "question": str(exc), "kind": exc.kind, "index": index, "context": context,
                    "date_to_confirm": exc.date_to_confirm, "amount": exc.amount,
                    "source": clause, "suggestion": exc.suggestion,
                }
            continue
        if txn:
            event_date = str(txn["date"])
            txn["parsed_phrase"] = clause
            transactions.append(_prepare_transaction(txn, raw_input))
    if pending:
        pending["ready"] = transactions
        pending["ready_reminders"] = reminders
        return {"clarification": pending}
    if reminders:
        if len(reminders) == 1 and not transactions:
            return {"reminder": reminders[0]}
        return {"transactions": transactions, "reminders": reminders, "raw_input": raw_input}
    if not transactions:
        return {"error": "No completed transaction to save."}
    if len(transactions) == 1:
        return transactions[0]
    return {"transactions": transactions, "raw_input": raw_input}


def extract_expense(user_message: str, *, allow_remote_amount=True) -> dict:
    """Return transactions, a targeted clarification, or an error."""
    user_message = user_message.strip()
    if not user_message:
        return {"error": "Enter a transaction to get started."}
    confirmation = CONFIRMATION.search(user_message)
    if confirmation and re.search(r"\b(?:not|never|don['’]t|can['’]t|cannot|shouldn['’]t)\s*$", user_message[:confirmation.start()].rstrip(" ,;"), re.I):
        confirmation = None
    text = user_message[:confirmation.start()].strip() if confirmation else user_message
    result = _extract_context({
        "raw_input": user_message, "clauses": _clauses(text), "today": date.today(),
        "answers": {}, "future_confirmed": bool(confirmation), "allow_remote_amount": allow_remote_amount,
    })
    # Keep the existing explicit-confirmation error for callers that only handle errors.
    if result.get("clarification", {}).get("kind") == "future":
        result["error"] = "Future dates require explicit confirmation. Add 'confirm future date' to proceed."
    return result


def resolve_clarification(pending: dict, reply: str) -> dict:
    """Apply a reply to the specific clause and revalidate the whole batch."""
    original_reply = reply.strip().rstrip("!.,?")
    reply = original_reply.lower()
    context = pending["context"]
    index = pending["index"]
    kind = pending["kind"]
    answers = context["answers"].get(index, {}).copy()
    yes = {"yes", "haan", "han", "ha", "ji haan", "ji han"}
    no = {"no", "nahi", "nahin", "ji nahi", "ji nahin"}
    try:
        original_loan = loan_intent(context["clauses"][index])
        reply_debt = debt_intent(original_reply)
        if original_loan and reply_debt and reply_debt["direction"] == "collect":
            payment_text, _, _ = _repayment_parts(context["clauses"][index])
            paid_amount = _reminder_amount(payment_text)
            due = _reminder_amount(original_reply)
            if paid_amount is None or due is None:
                raise ValueError("Say how much of the loan is still owed to you.")
            if due > paid_amount:
                raise ValueError(f"The repayment cannot exceed the {_rupees(paid_amount)} you lent.")
            answers.update(amount=paid_amount, due=due)
            if reply_debt["person"]:
                answers["repayment_person"] = reply_debt["person"]
        elif kind == "direction":
            intent = debt_intent(original_reply)
            if reply in {"pay", "to pay", "give", "देने हैं", "dena hai"}:
                direction = "pay"
            elif reply in {"collect", "to collect", "take", "लेने हैं", "lena hai"}:
                direction = "collect"
            else:
                direction = intent["direction"] if intent else None
            if direction not in {"collect", "pay"}:
                raise ValueError("Say “I need to pay” or “I need to collect”.")
            answers["debt_direction"] = direction
        elif kind == "net_salary":
            amount = _reminder_amount(original_reply)
            if amount is None or re.search(r"\b(?:tax|deduction)\b", reply) and not re.search(r"\b(?:after|net|credited|received)\b", reply):
                raise ValueError(pending["question"])
            answers["amount"] = amount
        elif kind in {"amount", "due"}:
            amount_reply = _apply_amount_corrections(original_reply)
            payment, repayment, person = _repayment_parts(amount_reply)
            # Older pending drafts asked users to choose between a payment and a named promise.
            if kind == "amount" and not repayment:
                promise = named_return(context["clauses"][index])
                if promise:
                    split = re.fullmatch(
                        r"(.+?)\s+and\s+(₹?\s*[\d,]+(?:\.\d+)?)\s+from\s+"
                        + re.escape(promise["person"]), amount_reply, re.I,
                    )
                    if split:
                        payment, repayment = split.groups()
                        person = promise["person"]
            if kind == "amount" and repayment and not STANDALONE_DEBT.match(context["clauses"][index]):
                paid_amount = _reminder_amount(payment)
                due = _reminder_amount(repayment)
                if not paid_amount or not due:
                    raise ValueError("Tell me what you paid and how much you expect back.")
                if due > paid_amount:
                    raise ValueError(f"The repayment cannot exceed the {_rupees(paid_amount)} you paid.")
                answers.update(amount=paid_amount, due=due)
                if person:
                    answers["repayment_person"] = person
                amount_reply = payment
            matches = _amount_candidates(amount_reply)
            if kind == "due" and reply in {"skip", "skip note", "skip repayment", "no", "nahi"}:
                answers["due"] = None
            elif kind == "amount" and reply in yes and pending.get("suggestion"):
                answers["amount"] = pending["suggestion"]
            elif len(matches) == 1 and not ALTERNATIVES.search(amount_reply) and not FOREIGN_CURRENCY.search(amount_reply):
                answers[kind] = _amount(matches[0])
                if kind == "due" and answers[kind] > pending["amount"]:
                    raise ValueError(f"The repayment cannot exceed the {_rupees(pending['amount'])} you paid.")
                if kind == "due" and person:
                    answers["repayment_person"] = person
            else:
                raise ValueError("Say one amount in rupees.")
        elif kind == "details":
            intent = debt_intent(original_reply)
            detail = original_reply if intent else AMOUNT_PATTERN.sub(" ", original_reply).strip()
            if not re.search(r"[^\W\d_]", detail) or reply in yes | no | {"all", "sab"}:
                raise ValueError("Tell me what the money was for. For example, say “rent” or “I received it”.")
            amount = pending["amount"]
            original_clause = context["clauses"][index]
            if amount is not None and TO_GIVE.search(detail):
                original_debt = STANDALONE_DEBT.match(original_clause)
                if original_debt and original_debt["to"]:
                    detail = original_clause
            date_text = DATE_PATTERN.search(original_clause)
            if date_text and not DATE_PATTERN.search(detail) and not answers.get("date"):
                answers["date"] = date_text[0]
            answers["details"] = detail if amount is not None else original_reply
            if amount is not None:
                answers["amount"] = amount
        elif kind == "person":
            person = re.sub(r"^(?:to|it was to|i owe)\s+", "", original_reply, flags=re.I)
            if not re.search(r"[^\W\d_]", person) or reply in yes | no:
                raise ValueError("Say the person’s name.")
            answers["person"] = person
        elif kind in {"refund", "payer"}:
            if reply not in yes | no:
                raise ValueError(pending["question"])
            answers[kind] = reply in yes
        else:
            if kind == "future" and reply in yes:
                # Use the date shown in the question, even if the reply arrives after midnight.
                answers["future"] = pending["date_to_confirm"]
            else:
                if not DATE_PATTERN.fullmatch(reply) or reply == "kal":
                    raise ValueError("Reply with a date such as 3 April 2026 or 2026-04-03.")
                answers["date"] = _resolve_date(reply, context["today"]).isoformat()
                answers.pop("future", None)
    except (ValueError, InvalidOperation, OverflowError) as exc:
        return {"clarification": {**pending, "reply_hint": str(exc)}}
    return _extract_context({**context, "answers": {**context["answers"], index: answers}})
