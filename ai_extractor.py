"""
ai_extractor.py — Groq-powered transaction extraction
------------------------------------------------------
Detects both DEBIT (expenses) and CREDIT (income) from natural language.
"""

import os
import json
import re
from datetime import date, timedelta
import streamlit as st

try:
    from groq import Groq
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
    "Food & Dining": ["food", "lunch", "dinner", "breakfast", "snack", "meal", "restaurant", "cafe", "ice cream"],
    "Groceries": ["grocery", "groceries", "supermarket", "vegetable", "milk"],
    "Transport": ["uber", "ola", "taxi", "cab", "petrol", "fuel", "bus", "train", "metro", "auto"],
    "Health & Medical": ["doctor", "hospital", "medicine", "pharmacy", "dental", "dentist"],
    "Entertainment": ["movie", "cinema", "netflix", "spotify", "game", "concert"],
    "Shopping": ["shopping", "clothes", "amazon", "flipkart", "mall"],
    "Utilities & Bills": ["bill", "electricity", "water", "internet", "wifi", "recharge", "phone bill"],
    "Education": ["course", "tuition", "school", "college", "book", "exam"],
    "Travel": ["trip", "flight", "hotel", "travel", "vacation"],
    "Personal Care": ["salon", "barber", "haircut", "spa", "grooming"],
    "Home & Maintenance": ["rent", "repair", "maintenance", "furniture", "home"],
    "Subscriptions": ["subscription", "prime", "netflix", "youtube premium"],
}

INCOME_HINTS = {
    "Salary": ["salary", "paycheck", "stipend"],
    "Freelance": ["freelance", "client", "project payment"],
    "Gift": ["gift", "present"],
    "Reimbursement": ["refund", "reimburse", "reimbursement"],
    "Investment Returns": ["interest", "dividend", "returns", "profit"],
    "Rental Income": ["rent received", "tenant"],
    "Other Income": ["received", "got", "income", "credit"],
}

DEBIT_VERBS = {"paid", "spent", "bought", "gave", "pay", "purchase"}
CREDIT_VERBS = {"received", "got", "earned", "credit", "income", "refunded"}

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


def _has_future_date_confirmation(user_message: str) -> bool:
    lowered = user_message.lower()
    if any(phrase in lowered for phrase in FUTURE_CONFIRM_PHRASES):
        return True
    return bool(re.search(r"\b(confirm|allow|approve|approved)\b.*\bfuture\b", lowered))


def _guard_future_date(resolved_date: str, user_message: str) -> str:
    try:
        resolved = date.fromisoformat(resolved_date)
    except ValueError:
        return resolved_date

    if resolved > date.today() and not _has_future_date_confirmation(user_message):
        raise ValueError("Future dates require explicit confirmation. Add 'confirm future date' to proceed.")
    return resolved_date


def _extract_json_candidate(raw: str):
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    obj_match = re.search(r"\{[\s\S]*\}", cleaned)
    if obj_match:
        return json.loads(obj_match.group(0))

    arr_match = re.search(r"\[[\s\S]*\]", cleaned)
    if arr_match:
        return {"transactions": json.loads(arr_match.group(0))}

    raise json.JSONDecodeError("No JSON found", cleaned, 0)


def _pick_category(note: str, txn_type: str, source_text: str = "") -> str:
    n = f"{note} {source_text}".lower()
    hints = INCOME_HINTS if txn_type == "credit" else DEBIT_HINTS
    for category, words in hints.items():
        if any(w in n for w in words):
            return category
    return "Other Income" if txn_type == "credit" else "Other"


def _cleanup_note(note: str) -> str:
    cleaned = re.sub(r"\b(and|then|also|for|to|on|at|in)\b", " ", note, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _normalize_merchant_text(cleaned)
    return cleaned[:50]


def _prepare_transaction(txn: dict, user_message: str) -> dict:
    prepared = dict(txn)
    prepared["transaction_type"] = "credit" if prepared.get("transaction_type") == "credit" else "debit"
    prepared["amount"] = float(prepared.get("amount", 0) or 0)
    prepared["category"] = prepared.get("category", "Other")
    prepared["date"] = _guard_future_date(_resolve_date(str(prepared.get("date", "today"))), user_message)
    prepared["note"] = _normalize_merchant_text(str(prepared.get("note", "")))
    if not prepared["note"]:
        prepared["note"] = "transaction"

    merchant_match = re.search(
        r"\b(uber|ola|swiggy|zomato|amazon|flipkart|netflix|spotify)\b",
        f"{prepared['note']} {user_message}",
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


def _fallback_extract(user_message: str) -> dict:
    text = re.sub(r"(?<=\d),(?=\d)", "", user_message)
    amt_pattern = re.compile(r"(?i)(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)")
    matches = list(amt_pattern.finditer(text))
    if not matches:
        return {"error": "No amount found"}

    date_match = re.search(
        r"\b(today|yesterday|tomorrow|last\s+\w+|this\s+\w+|\d+\s+days?\s+ago|\d{4}-\d{2}-\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    try:
        date_value = _guard_future_date(_resolve_date(date_match.group(1) if date_match else "today"), user_message)
    except ValueError as exc:
        return {"error": str(exc)}

    txns = []
    last_type = "debit"
    for i, m in enumerate(matches):
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = text[max(0, m.start() - 25):m.start()].lower()
        after = text[m.end():next_start]
        fragment = f"{before} {after}".lower()

        if any(v in fragment for v in CREDIT_VERBS):
            txn_type = "credit"
        elif any(v in fragment for v in DEBIT_VERBS):
            txn_type = "debit"
        else:
            txn_type = last_type
        last_type = txn_type

        note = _cleanup_note(f"{before} {after}")
        if not note or note in {"today", "yesterday", "tomorrow"}:
            note = _cleanup_note(user_message)
        if not note:
            note = "transaction"

        txns.append(
            _prepare_transaction(
                {
                    "transaction_type": txn_type,
                    "amount": float(m.group(1)),
                    "category": _pick_category(note, txn_type, user_message),
                    "date": date_value,
                    "note": note,
                },
                user_message,
            )
        )

    if len(txns) == 1:
        return txns[0]
    return {"transactions": txns, "raw_input": user_message}


def _resolve_date(date_str: str) -> str:
    today = date.today()
    d = date_str.lower().strip()
    if d in ("today", "now", ""):
        return str(today)
    if d in ("yesterday", "yday"):
        return str(today - timedelta(days=1))
    if d == "tomorrow":
        return str(today + timedelta(days=1))
    days_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    m = re.match(r"last\s+(\w+)", d)
    if m and m.group(1) in days_map:
        target = days_map[m.group(1)]
        delta = (today.weekday() - target) % 7 or 7
        return str(today - timedelta(days=delta))
    m = re.match(r"(\d+)\s+days?\s+ago", d)
    if m:
        return str(today - timedelta(days=int(m.group(1))))
    m = re.match(r"this\s+(\w+)", d)
    if m and m.group(1) in days_map:
        delta = (today.weekday() - days_map[m.group(1)]) % 7
        return str(today - timedelta(days=delta))
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        return d
    return str(today)


def _build_prompt(user_message: str) -> str:
    today_str = date.today().strftime("%A, %d %B %Y")
    expense_cats = "\n".join(f"  - {c}" for c in EXPENSE_CATEGORIES)
    income_cats  = "\n".join(f"  - {c}" for c in INCOME_CATEGORIES)

    return f"""You are a personal finance assistant. Today is {today_str}.

Extract all transactions from the user message and return ONLY a raw JSON object.
No explanation, no markdown, no code blocks — just the JSON.

If the message contains more than one transaction, return them in the same order.
If there is only one transaction, still return it inside the transactions array.

Determine transaction_type:
- "debit"  = money going OUT (paid, spent, bought, expense, bill, fee)
- "credit" = money coming IN (received, got, earned, salary, income, gift, refund, reimbursement)

Expense categories (use for debit):
{expense_cats}

Income categories (use for credit):
{income_cats}

Return this exact JSON:
{{
    "transactions": [
        {{
            "transaction_type": "debit" or "credit",
            "amount": <number in rupees, required>,
            "category": <pick best match from the appropriate list above>,
            "date": <"today", "yesterday", "last monday", or "YYYY-MM-DD">,
            "note": <short description, max 50 chars>
        }}
    ]
}}

If no numeric amount found, return: {{"error": "No amount found"}}

User message: "{user_message}"

JSON:"""


def extract_expense(user_message: str) -> dict:
    """
    Parse a natural language transaction message.
    Returns dict with: transaction_type, amount, category, date, note
    Or: dict with 'error' key.
    """
    rule_result = _fallback_extract(user_message)
    if "error" not in rule_result:
        return rule_result
    if "Future dates require explicit confirmation" in str(rule_result.get("error", "")):
        return rule_result

    api_key = (
        os.environ.get("GROQ_API_KEY")
        or st.secrets.get("GROQ_API_KEY", None)
    )

    if not api_key:
        return rule_result
    if not _GROQ_AVAILABLE:
        return {"error": "groq package not installed. Run: pip install groq"}

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": _build_prompt(user_message)}],
            temperature=0.1,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()
        data = _extract_json_candidate(raw)

        if "error" in data:
            return {"error": data["error"]}

        if isinstance(data, dict) and "transactions" in data:
            transactions = data.get("transactions", [])
        else:
            transactions = [data]

        if not isinstance(transactions, list) or not transactions:
            return {"error": "AI did not return any transactions."}

        normalized = []
        for item in transactions:
            if not isinstance(item, dict):
                continue
            if not item.get("amount"):
                return {"error": "Could not find a numeric amount in one of the transactions."}

            try:
                normalized.append(_prepare_transaction(item, user_message))
            except ValueError as exc:
                return {"error": str(exc)}

        if not normalized:
            return {"error": "AI did not return any valid transactions."}

        if len(normalized) == 1:
            return normalized[0]

        return {"transactions": normalized, "raw_input": user_message}

    except json.JSONDecodeError:
        return _fallback_extract(user_message)
    except Exception as e:
        err = str(e)
        if "api_key" in err.lower() or "authentication" in err.lower():
            return {"error": "Invalid GROQ_API_KEY. Check console.groq.com"}
        if "rate" in err.lower():
            return {"error": "Rate limit hit. Wait a moment and try again."}
        # Keep app usable even if model/network fails by parsing locally.
        fallback = _fallback_extract(user_message)
        if "error" not in fallback:
            return fallback
        return {"error": f"AI error: {err[:120]}"}