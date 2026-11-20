"""Apply explicit corrections and category preferences to an unsaved draft."""

from copy import deepcopy
from decimal import Decimal
import re

from ai_extractor import (
    ALTERNATIVES, EXPENSE_CATEGORIES, FOREIGN_CURRENCY, INCOME_CATEGORIES,
    _amount, _amount_candidates, _apply_amount_corrections, _clauses,
)
from voice_input import normalize_voice_transcript


def draft_entries(result):
    if reminder := result.get("reminder"):
        return [], [reminder]
    return result.get("transactions", [result]), result.get("reminders", [])


def attach_source_quotes(result, original):
    """Match local parser phrases back to the original text where the match is unique."""
    def comparable(phrase):
        return " ".join(phrase.casefold().strip(" ,.;!?").split())

    matches = {}
    parts = re.split(r"(?<=[.!?।;])\s+|,\s+|\s+(?:and|aur)\s+|\s+और\s+", original, flags=re.I)
    # Use only complete snippets. A quote containing several clauses would be misleading.
    for part in [original, *parts]:
        clauses = _clauses(normalize_voice_transcript(part))
        if len(clauses) == 1:
            matches.setdefault(comparable(clauses[0]), set()).add(part.strip())
    if pending := result.get("clarification"):
        rows = pending.get("ready", []) + pending.get("ready_reminders", [])
    elif "error" not in result:
        transactions, reminders = draft_entries(result)
        rows = transactions + reminders
    else:
        return
    for row in rows:
        if row.get("parsed_phrase"):
            candidates = matches.get(comparable(row["parsed_phrase"]), set())
            if len(candidates) == 1:
                row["source"] = next(iter(candidates))


def edit_amount(draft, group, index, spoken):
    text = normalize_voice_transcript(spoken)
    # The user can say that an attached reminder should stay as it is.
    parts = re.split(r"(?:[.!;,]|\band\b|\baur\b)\s*(?=keep\b|baaki\b)", text, maxsplit=1, flags=re.I)
    change = _apply_amount_corrections(parts[0])
    amounts = _amount_candidates(change)
    if len(amounts) > 1:
        replacement = re.search(r"\bfrom\b.+?\bto\b", change, re.I)
        if replacement:
            amounts = _amount_candidates(change[replacement.end():])
    if len(amounts) != 1 or ALTERNATIVES.search(change) or FOREIGN_CURRENCY.search(change):
        raise ValueError("Say one new amount in rupees, such as “change it to 2800”.")
    amount = _amount(amounts[0])
    revised = deepcopy(draft)
    transactions, reminders = draft_entries(revised)
    if group == "reminder":
        target = reminders[index]
    elif group == "repayment":
        target = transactions[index]["repayment"]
    else:
        target = transactions[index]
    target["amount"] = float(amount)
    for transaction_index, transaction in enumerate(transactions):
        attached = transaction.get("repayment", {}).get("amount", 0)
        total = Decimal(str(attached)) + sum(
            Decimal(str(row["amount"])) for row in reminders
            if row.get("transaction_index") == transaction_index
        )
        if total > Decimal(str(transaction["amount"])):
            raise ValueError("The total repayment cannot exceed what you paid. Correct the repayment first.")
    target["correction"] = spoken
    return revised


def preference_phrase(phrase):
    return " ".join(phrase.strip(" \t\"'“”‘’").casefold().split())


def teach_command(message):
    match = re.fullmatch(
        r"\s*(?:when i say|remember that)\s+(.+?)\s*,?\s+(?:put it under|categorize it as|means)\s+(.+?)\s*[.!]?\s*",
        message, re.I,
    )
    if not match:
        return None
    phrase, category = preference_phrase(match[1]), match[2].strip().casefold()
    categories = {label.casefold(): label for label in EXPENSE_CATEGORIES + INCOME_CATEGORIES}
    categories["home"] = "Home & Maintenance"
    categories["food"] = "Food & Dining"
    if not phrase or len(phrase) > 100 or category not in categories:
        raise ValueError("Use a short phrase and a ledger category, such as Home or Food.")
    return phrase, categories[category]


def apply_preferences(result, preferences):
    if not preferences or "error" in result:
        return
    if "clarification" in result:
        rows = result["clarification"].get("ready", [])
    else:
        rows, _ = draft_entries(result)
    for row in rows:
        categories = INCOME_CATEGORIES if row["transaction_type"] == "credit" else EXPENSE_CATEGORIES
        source = row.get("source") or row.get("parsed_phrase") or row["note"]
        source = preference_phrase(normalize_voice_transcript(source))
        for phrase, category in sorted(preferences.items(), key=lambda item: len(item[0]), reverse=True):
            needle = preference_phrase(normalize_voice_transcript(phrase))
            if needle and category in categories and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", source):
                row["category"] = category
                break
