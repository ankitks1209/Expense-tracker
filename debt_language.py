"""Recognize who still needs to pay, independently of the amount's word order."""

import re


PAY = re.compile(
    r"\bi\s+(?:still\s+)?owe\b|\b(?:have|need) to (?:give|pay)\b|\bi (?:have to|need to|will) (?:return|repay)\b|"
    r"\bit (?:is|was) to give\b|\bstill to (?:give|pay)\b|"
    r"देने\s+(?:हैं|है)|\b(?:dene|dena)\s+(?:hain|hai)\b", re.I,
)
COLLECT = re.compile(
    r"\bowes? me\b|\bi (?:have|need) to (?:take|get|collect|receive)\b|"
    r"\bi(?:'ll| will| should| expect to) (?:get|receive)\b.*?\bback\b|"
    r"लेने\s+(?:हैं|है)|\b(?:lene|lena)\s+(?:hain|hai)\b", re.I,
)
LENDING = re.compile(
    r"\b(?:lent|loaned)\b|\b(?:udhaar|udhar)\s+(?:diya|diye)\b|"
    r"उधार\s+(?:diya|diye|दिया|दिए)|\b(?:gave|paid)\b[^.;!?]*\b(?:as a loan|on loan)\b", re.I,
)
PROMISE_RETURN = re.compile(
    r"\b(?:he|she|they)\s+will\s+(?:return|repay|give|pay)\b|"
    r"(?:तो\s+)?(?:वो|वह|वे)\s+[^.;!?]*?(?:wapas|वापस)\s+(?:देगा|देगी|देंगे)|"
    r"\b(?:woh?|voh?)\b[^.;!?]*?\b(?:wapas|vaapas)\s+(?:dega|degi|denge)\b", re.I,
)
INVALID_NAMES = {
    "i", "me", "my", "you", "someone", "they", "he", "she", "it", "still", "from",
    "to", "mujhe", "mujhko", "mujh", "mere", "mereko", "ko", "se", "aur",
    "मुझे", "मेरे", "को", "से", "उसमें", "जिसमें", "जिसमे", "उसने", "क्योंकि",
    "give", "pay", "get", "take", "collect", "receive",
}


# A named promise followed by a monetary amount, e.g. “Aditya will return ₹1,500”.
# Require the end of the promise so “return 1500 to Rahul” cannot credit the user.
NAMED_RETURN = re.compile(
    r"\b(?P<person>[^\W\d_]+)\s+will\s+(?:return|repay)(?:\s+me)?\s+"
    r"(?=(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d+)?(?:\s+rupees?)?(?:\s+to me)?"
    r"\s*(?:$|[.!?;](?!\d)|,\s+|\band\b))", re.I,
)


def named_return(text):
    match = NAMED_RETURN.search(text)
    if match and match["person"].casefold() not in INVALID_NAMES | {"we", "it"}:
        return match
    return None


def debt_intent(text):
    pay = PAY.search(text)
    promise = named_return(text)
    collect = COLLECT.search(text) or promise
    if not pay and not collect:
        return None
    direction = "ambiguous" if pay and collect else "pay" if pay else "collect"
    person = promise["person"].capitalize() if promise and direction == "collect" else ""
    patterns = []
    if direction != "collect":
        patterns += [
            r"\bi\s+(?:still\s+)?owe\s+(?P<name>[^\d₹,.;!?]+?)(?=\s+(?:₹?\s*\d|tomorrow\b|today\b)|[.,;!?]|$)",
            r"(?P<name>[^\s,.;!?]+)\s+(?:को|ko)(?=\s|[.,;!?]|$)",
            r"\bto\s+(?P<name>[^\d₹,.;!?]+?)(?=\s+(?:for|on|today|tomorrow)\b|[.,;!?]|$)",
        ]
    if direction != "pay":
        patterns += [
            r"(?P<name>[^\s,.;!?]+)\s+(?:still\s+)?owes? me\b",
            r"(?P<name>[^\s,.;!?]+)\s+(?:से|se)(?=\s|[.,;!?]|$)",
            r"\bfrom\s+(?P<name>[^\d₹,.;!?]+?)(?=\s+(?:for|on|today|tomorrow)\b|[.,;!?]|$)",
        ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            candidate = match["name"].strip(" .,!?'")
            if (re.search(r"[^\W\d_]", candidate) and candidate.casefold() not in INVALID_NAMES
                    and not candidate.casefold().startswith(("have ", "need "))):
                person = candidate[:1].upper() + candidate[1:]
                break
        if person:
            break
    return {
        "direction": direction, "person": person,
        "start": min(match.start() for match in (pay, collect) if match),
    }


def loan_intent(text):
    if not LENDING.search(text):
        return None
    patterns = (
        r"(?P<name>[^\s,.;!?]+)\s+(?:को|ko)(?=\s|[.,;!?]|$)",
        r"\bto\s+(?P<name>[^\d₹,.;!?]+?)(?=\s+(?:for|on|today|tomorrow)\b|[.,;!?]|$)",
        r"\b(?:lent|loaned|gave)\s+(?P<name>[^\d₹,.;!?]+?)(?=\s+₹?\s*\d)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            person = match["name"].strip()
            if person.casefold() not in INVALID_NAMES and re.search(r"[^\W\d_]", person):
                return {"person": person[:1].upper() + person[1:]}
    return {"person": ""}


# Completed repayments identify both the direction and the person on the other side.
_PERSON = r"(?P<person>[^\W\d_][\w\u0900-\u097f'-]*)"
_COMPLETED = (
    ("credit", rf"^{_PERSON}\s+(?:has\s+)?(?:returned\s+me|repaid\s+me|paid\s+me\s+back)\b"),
    ("debit", rf"^i\s+(?:have\s+)?(?:repaid\s+|paid\s+){_PERSON}\s+back\b"),
    ("debit", rf"^i\s+(?:have\s+)?repaid\s+{_PERSON}(?=\s+₹?\s*\d)"),
    ("debit", rf"^i\s+(?:have\s+)?returned\s+(?:₹?\s*[\d,.]+)\s+to\s+{_PERSON}"),
    ("credit", rf"^{_PERSON}\s+(?:ne|ने)\s+(?:mujhe|मुझे)\s+.*?\b(?:wapas|waapas)\s+(?:diye|diya)\b"),
)


def completed_repayment(text):
    for direction, pattern in _COMPLETED:
        match = re.search(pattern, text.strip(), re.I)
        if match:
            return direction, match["person"]
    return None


def person_key(name):
    # A dictated Hindi name can appear in a different script on successive turns.
    key = name.strip().casefold()
    return {"आदित्य": "aditya"}.get(key, key)
