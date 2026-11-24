"""Locate quoted amounts inside the surrounding user statements and corrections."""

from dataclasses import dataclass
import re

from ai_extractor import (
    CORRECTION, CREDIT, DEBIT, OWES_ME, STANDALONE_DEBT, TO_GIVE,
    UPCOMING_REPAYMENT, _amount, _amount_candidates, _apply_amount_corrections,
)
from voice_input import normalize_voice_transcript
from debt_language import PROMISE_RETURN, debt_intent, loan_intent, named_return


BOUNDARY = re.compile(
    r"[;\n।]+|(?<=[.!?])\s+"
    r"|\s+(?:and then|and also|and|then|aur|और)\s+"
    r"|,\s+(?=(?:(?:i|we)\s+)?(?:paid|spent|gave|received|got|earned)\b)",
    re.I,
)
SUBJECT_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
COMMON_WORDS = {
    "i", "we", "you", "the", "a", "an", "it", "was", "is", "for", "to", "of", "in",
    "paid", "spent", "received", "got", "gave", "amount", "rupees", "rs", "no",
    "sorry", "actually", "not", "that", "this", "mean", "change", "make", "instead",
    "nahi", "nahin", "tha", "ke", "ka", "ki", "ko", "aur", "diya", "diye",
    "how", "much", "did", "do", "does", "pay", "personally", "record", "correct", "which",
}


@dataclass
class Statement:
    turn: int
    start: int
    end: int
    text: str
    superseded: bool = False

    @property
    def normalized(self):
        return _apply_amount_corrections(normalize_voice_transcript(self.text))


def _subject_words(text):
    words = SUBJECT_WORDS.findall(normalize_voice_transcript(text).casefold())
    return set(words) - COMMON_WORDS


def _is_correction(text):
    normalized = normalize_voice_transcript(text).strip()
    return bool(CORRECTION.match(" " + normalized))


def _split_statements(turn_index, text):
    statements = []
    start = 0
    for boundary in [*BOUNDARY.finditer(text), None]:
        end = boundary.start() if boundary else len(text)
        phrase = text[start:end].strip()
        if phrase:
            name_continuation = bool(
                statements and debt_intent(normalize_voice_transcript(statements[-1].text))
                and re.match(r"[^\s,.;!?]+\s+(?:से|को|se|ko)(?=\s|[.,;!?]|$)", phrase, re.I)
                and not _amount_candidates(normalize_voice_transcript(phrase))
            )
            loan_continuation = bool(
                statements and loan_intent(normalize_voice_transcript(statements[-1].text))
                and PROMISE_RETURN.search(normalize_voice_transcript(phrase))
            )
            if statements and (_is_correction(phrase) or name_continuation or loan_continuation):
                previous = statements[-1]
                previous.end = end
                previous.text = text[previous.start:end].strip()
            else:
                statements.append(Statement(turn_index, start, end, phrase))
        if boundary:
            start = boundary.end()
    return statements


def conversation_statements(turns):
    statements = []
    for turn_index, turn in enumerate(turns):
        if turn["role"] != "user":
            continue
        current = _split_statements(turn_index, turn["content"])
        question = turns[turn_index - 1]["content"] if turn_index and turns[turn_index - 1]["role"] == "assistant" else ""
        bare_amount_reply = bool(
            current and len(current) == 1 and len(_amount_candidates(current[0].normalized)) == 1
            and not _subject_words(current[0].text)
            and re.search(r"how much|which amount|did you pay", question, re.I)
        )
        if current and (_is_correction(current[0].text) or bare_amount_reply) and statements:
            correction = current[0]
            words = _subject_words(correction.text)
            candidates = [statement for statement in statements if not statement.superseded
                          and (_amount_candidates(statement.normalized)
                               or CREDIT.search(statement.normalized) or DEBIT.search(statement.normalized)
                               or OWES_ME.search(statement.normalized))]
            named = [statement for statement in candidates if _subject_words(statement.text) & words]
            if named:
                candidates = named
            elif turn_index and turns[turn_index - 1]["role"] == "assistant":
                question_words = _subject_words(turns[turn_index - 1]["content"])
                asked_about = [statement for statement in candidates
                               if _subject_words(statement.text) & question_words]
                if asked_about:
                    candidates = asked_about
            if len(candidates) == 1:
                # Keep its payment context while replacing its old amount evidence.
                previous = candidates[0]
                previous.superseded = True
                marker = "No, " if bare_amount_reply else ""
                correction.text = previous.text + ". " + marker + correction.text
            else:
                # A correction with no unique target cannot justify the older amounts.
                for previous in candidates:
                    previous.superseded = True
        statements.extend(current)
    return statements


def evidence_for(source, turns, statements):
    """Return the complete statement for a quote with a unique, current location."""
    source = source.rstrip(" .!?;।")
    if not source:
        raise ValueError("The source quote needs a transaction statement.")
    matches = []
    for turn_index, turn in enumerate(turns):
        if turn["role"] != "user":
            continue
        for match in re.finditer(re.escape(source), turn["content"]):
            containing = [statement for statement in statements if statement.turn == turn_index
                          and statement.start <= match.start() and statement.end >= match.end()]
            if len(containing) == 1:
                statement = containing[0]
                if not statement.superseded:
                    matches.append(statement)
    unique = {(statement.turn, statement.start, statement.end): statement for statement in matches}
    if len(unique) != 1:
        raise ValueError("The quote needs one complete, current transaction statement.")
    return next(iter(unique.values()))


def amount_positions(statement, amount):
    return [
        (match.start(), match.end())
        for match in _amount_candidates(statement.normalized)
        if _amount(match) == amount
    ]


def payment_status(statement, amount):
    """Distinguish the paid amount from the expected repayment in a split statement."""
    text = statement.normalized
    intent = debt_intent(text)
    if intent:
        prefix = text[:intent["start"]]
        if not (_amount_candidates(prefix) and (CREDIT.search(prefix) or DEBIT.search(prefix))):
            return "pending", text
    owed, upcoming, promised = OWES_ME.search(text), UPCOMING_REPAYMENT.search(text), PROMISE_RETURN.search(text)
    debt = STANDALONE_DEBT.match(text)
    if debt or TO_GIVE.search(text):
        return "pending", text
    marker = min((match.start() for match in (owed, upcoming, promised, named_return(text)) if match), default=len(text))
    before, after = text[:marker], text[marker:]
    paid = [_amount(match) for match in _amount_candidates(before)]
    due = [_amount(match) for match in _amount_candidates(after)]
    if loan_intent(text) and amount in paid:
        return "completed", before
    if amount in due and amount not in paid:
        return "pending", after
    if amount in due and amount in paid and after:
        raise ValueError("The same amount appears in both payment and repayment.")
    return "completed", before


def money_direction(text):
    credit, debit = CREDIT.search(text), DEBIT.search(text)
    if credit and debit:
        return "ambiguous"
    if credit and not debit:
        return "credit"
    if debit and not credit:
        return "debit"
    return None


def reminder_direction(text):
    if loan_intent(text):
        return "collect"
    intent = debt_intent(text)
    if intent:
        return intent["direction"] if intent["direction"] != "ambiguous" else None
    debt = STANDALONE_DEBT.match(text)
    if debt:
        return "pay" if debt["to"] else "collect"
    if TO_GIVE.search(text) or re.search(r"देने\s+हैं?(?=\s|[.!?,]|$)", text):
        return "pay"
    if OWES_ME.search(text) or UPCOMING_REPAYMENT.search(text) or re.search(r"लेने\s+हैं?(?=\s|[.!?,]|$)", text):
        return "collect"
    return None
