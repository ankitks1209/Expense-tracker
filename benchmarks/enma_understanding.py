"""Offline pilot for measuring Enma's transcript parser and follow-up handling."""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

import ai_extractor
from understanding import MODEL, UnderstandingError, ModelUnavailable, request_proposal, validate_proposal, groq_key
from voice_input import TranscriptionError, gnani_api_key, normalize_voice_transcript, transcribe_recording


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    # A case can expect a ledger entry (credit/debit) or a reminder (collect/pay).
    # Score kind, amount, person, category, date and linked transaction position.
    expected: tuple
    question: str = ""
    reply: str = ""


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat() if isinstance(offset, int) else offset


def received(amount, category="Other Income", when=0):
    return ("credit", amount, "", category, day(when), 0)


def spent(amount, category="Other", when=0):
    return ("debit", amount, "", category, day(when), 0)


def collect(amount, name, parent=0):
    return ("collect", amount, name.casefold(), "", "", parent)


def pay(amount, name, when=""):
    return ("pay", amount, name.casefold(), "", day(when), 0)


DEV = (
    Case("simple food", "paid 240 for lunch today", (spent(240, "Food & Dining"),)),
    Case("simple Hindi fare", "आज मेट्रो के लिए ₹६० दिए।", (spent(60, "Transport"),)),
    Case("simple Hinglish", "maine grocery ke liye 850 diye", (spent(850, "Groceries"),)),
    Case("salary", "received 32k salary", (received(32000, "Salary"),)),
    Case("decimal", "paid ₹1,250.50 for the dentist", (spent(1250.50, "Health & Medical"),)),
    Case("mixed directions", "got 5500 salary and paid 550 for petrol", (received(5500, "Salary"), spent(550, "Transport"))),
    Case("two amounts and a count", "paid 850 for 2 train tickets and 120 for coffee", (spent(850, "Transport"), spent(120, "Food & Dining"))),
    Case("two dated expenses", "paid 180 for lunch yesterday and 320 for groceries today", (spent(180, "Food & Dining", -1), spent(320, "Groceries"))),
    Case("rent correction", "rent was 5000. No, 4000.", (spent(4000, "Home & Maintenance"),)),
    Case("repeated no", "I paid 5000 for rent. No, no, 4000.", (spent(4000, "Home & Maintenance"),)),
    Case("Romanized correction", "maine kiraya 5500 diya, nahi nahi 4500", (spent(4500, "Home & Maintenance"),)),
    Case("Hindi correction", "मैंने किराया ₹५००० दिया, नहीं ₹४०००।", (spent(4000, "Home & Maintenance"),)),
    Case("balance in Hindi", "3000 मिले, उसमें से 2000 नई 1900 दोस्त को दिए। बाकी के 1100 में से 500 का खाना खाया और बाकी की save कर ली।",
         (received(3000, "Other Income"), spent(1900, "Other"), spent(500, "Food & Dining"))),
    Case("balance in English", "I received 3000. I gave a friend 1900. From the remaining 1100 I spent 500 on food and saved the rest.",
         (received(3000, "Other Income"), spent(1900, "Other"), spent(500, "Food & Dining"))),
    Case("balance in Hinglish", "3000 mile, usme se 1900 dost ko diye aur baki ke 1100 mein se 500 ka khana khaya aur baki save kar li",
         (received(3000, "Other Income"), spent(1900, "Other"), spent(500, "Food & Dining"))),
    Case("savings only", "set aside 800 for later", ()),
    Case("uncompleted card charge", "did not pay 800 for dinner; card declined", ()),
    Case("uncompleted Hindi charge", "आज लंच के लिए 500 नहीं दिए।", ()),
    Case("obvious refund", "received a 350 refund from Amazon", (received(350, "Reimbursement"),)),
    Case("refund to clarify", "refund 350 from Amazon", (received(350, "Reimbursement"),), "refund", "yes"),
    Case("pending refund", "refund 350 from Amazon", (), "refund", "no"),
    Case("split share unclear", "paid 500 for dinner, split with Rahul", (spent(250, "Food & Dining"),), "amount", "250"),
    Case("split share specified", "the dinner total was 900, my share was 300", (spent(300, "Food & Dining"),)),
    Case("split and unrelated expense", "paid 500 for dinner, split with Rahul and paid 240 for Uber",
         (spent(250, "Food & Dining"), spent(240, "Transport")), "amount", "250"),
    Case("explicit movie repayment", "I paid 3000 for a movie and I need to take 1500 back from Aditya",
         (spent(3000, "Entertainment"), collect(1500, "Aditya", 1))),
    Case("movie reply gives two amounts", "3000 movie के लगे, जिसमें से 1500 लेने हैं मेरे को।",
         (spent(3000, "Entertainment"), collect(1500, "Aditya", 1)), "amount", "I paid 3000 and have to take 1500 back from Aditya"),
    Case("half split", "I paid 1200 for dinner and split it in half with Rahul",
         (spent(1200, "Food & Dining"), collect(600, "Rahul", 1)), "due", "600"),
    Case("someone owes me", "Rahul owes me 500 for tickets", (collect(500, "Rahul"),)),
    Case("I owe someone", "I owe Aditya 300 tomorrow", (pay(300, "Aditya", 1),)),
    Case("I owe in Hindi", "मुझे आदित्य को ५०० रुपये देने हैं।", (pay(500, "आदित्य"),)),
    Case("owe in a Hindi list", "500 का खाना खाया और 300 मेरे को देने हैं आदित्य को।", (spent(500, "Food & Dining"), pay(300, "आदित्य"))),
    Case("payment planned", "planning to pay 650 for the movie", ()),
    Case("amount missing", "paid for coffee", (spent(120, "Food & Dining"),), "amount", "120"),
    Case("two possible amounts", "paid 400 or 450 for dinner", (spent(450, "Food & Dining"),), "amount", "450"),
    Case("ambiguous date", "paid 500 on 03/04 for dinner", (spent(500, "Food & Dining", "2025-04-03"),), "date", "3 April 2025"),
    Case("explicit future date", "paid 500 tomorrow for groceries", (spent(500, "Groceries", 1),), "future", "yes"),
    Case("amount with no purpose", "850", (spent(850, "Transport"),), "details", "petrol"),
    Case("another person paid", "my friend paid 650 for dinner", (), "payer", "no"),
    Case("two corrections", "paid 900, no 800, actually 750 for groceries", (spent(750, "Groceries"),)),
    Case("refund mixed with expense", "got back 240 from Amazon and paid 120 for coffee", (received(240, "Reimbursement"), spent(120, "Food & Dining"))),
)


HOLDOUT = (
    Case("balance without punctuation", "I got 2800 from my cousin out of that I gave my friend 1600 and from what was left I spent 400 on lunch",
         (received(2800, "Other Income"), spent(1600, "Other"), spent(400, "Food & Dining"))),
    Case("Devanagari mixed directions", "४८०० मिले। फिर १२५० किराया दिया और ३०० पेट्रोल के लिए दिए।",
         (received(4800, "Other Income"), spent(1250, "Home & Maintenance"), spent(300, "Transport"))),
    Case("correction after payee", "I paid 760 to the plumber. Sorry, it was 670.", (spent(670, "Home & Maintenance"),)),
    Case("repayment without a bill", "Neha still owes me 425 for the cab", (collect(425, "Neha"),)),
    Case("several outstanding debts", "I owe Maya 500 and I owe Rohan 250", (pay(500, "Maya"), pay(250, "Rohan"))),
    Case("settled versus expected", "I paid 1600 for the cab and got 800 back from Kavya", (spent(1600, "Transport"), received(800, "Reimbursement"))),
    Case("count beside actual amount", "spent 450 on 3 kg of rice and 90 on tea", (spent(450, "Groceries"), spent(90, "Food & Dining"))),
    Case("negation alongside a real expense", "did not pay 700 for shoes, but paid 200 for lunch", (spent(200, "Food & Dining"),)),
    Case("Hindi pending payer", "४५० देने हैं", (pay(450, "नील"),), "person", "नील"),
    Case("correction in a reply", "paid 560 or 650 for transport", (spent(560, "Transport"),), "amount", "650 no 560"),
)


def signature(result):
    if "clarification" in result:
        return None
    if "error" in result:
        return ()
    transactions = result.get("transactions", [result] if "transaction_type" in result else [])
    reminders = result.get("reminders", [result["reminder"]] if "reminder" in result else [])
    entries = []
    for position, row in enumerate(transactions, start=1):
        entries.append((row["transaction_type"], row["amount"], "", row["category"], row["date"], 0))
        if repayment := row.get("repayment"):
            entries.append(("collect", repayment["amount"], repayment["person"].casefold(), "", repayment.get("due_date") or "", position))
    for row in reminders:
        index = row.get("transaction_index")
        parent = index + 1 if index is not None else 0
        entries.append((row["direction"], row["amount"], row["person"].casefold(), "", row.get("due_date") or "", parent))
    return tuple(sorted(entries))


def local_parser(turns, pending=None):
    message = normalize_voice_transcript(turns[-1]["content"])
    return ai_extractor.resolve_clarification(pending, message) if pending else ai_extractor.extract_expense(message)


def evaluate(cases, run=local_parser, *, verbose=False):
    correct_first, correct_final, unnecessary, wrong_draft, missed, correct_questions = (0,) * 6
    unavailable = rejected = 0
    missing_entries, extra_entries = 0, 0
    started = monotonic()
    for case in cases:
        turns = [{"role": "user", "content": case.text}]
        try:
            result = run(turns)
        except UnderstandingError as exc:
            unavailable += isinstance(exc, ModelUnavailable)
            rejected += not isinstance(exc, ModelUnavailable)
            missing_entries += len(case.expected)
            if verbose:
                print(f"{case.name}: {exc}")
            continue
        pending = result.get("clarification")
        question = pending["kind"] if pending else ""
        expected = tuple(sorted(case.expected))
        first = signature(result)
        question_ok = question == case.question
        correct_first += question_ok and (bool(question) or first == expected)
        correct_questions += bool(case.question) and question_ok
        unnecessary += bool(question) and not case.question
        missed += bool(case.question) and not question
        wrong_draft += bool(first) and (first != expected or bool(case.question))
        if pending and case.reply:
            turns += [{"role": "assistant", "content": pending["question"]}, {"role": "user", "content": case.reply}]
            try:
                result = run(turns, pending)
            except UnderstandingError as exc:
                unavailable += isinstance(exc, ModelUnavailable)
                rejected += not isinstance(exc, ModelUnavailable)
                missing_entries += len(case.expected)
                if verbose:
                    print(f"{case.name}: {exc}")
                continue
        final = signature(result)
        correct_final += final == expected
        actual, wanted = Counter(final or ()), Counter(expected)
        missing_entries += sum((wanted - actual).values())
        extra_entries += sum((actual - wanted).values())
        if verbose and (not question_ok or final != expected):
            print(f"{case.name}: asked {question or 'nothing'} (expected {case.question or 'nothing'}); "
                  f"draft {final!r} (expected {expected!r})")
    print(f"Correct first action: {correct_first}/{len(cases)}")
    print(f"Exact ledger/reminders after at most one reply: {correct_final}/{len(cases)}")
    print(f"Correct question type: {correct_questions}/{sum(bool(case.question) for case in cases)}")
    print(f"Unnecessary follow-ups: {unnecessary} · Missed follow-ups: {missed} · Wrong drafts offered: {wrong_draft}")
    print(f"Missing entries: {missing_entries} · Unexpected entries: {extra_entries} · Elapsed: {monotonic() - started:.1f}s")
    print(f"Provider unavailable: {unavailable} · Draft rejected: {rejected}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--verbose", action="store_true", help="Show failed cases.")
    parser.add_argument("--model", nargs="?", const=MODEL, help="Also test Groq using only these fictional inputs.")
    parser.add_argument("--limit", type=int, help="Run only the first N cases in the split.")
    parser.add_argument("--request-interval", type=float, default=0, help="Seconds between Groq request starts.")
    parser.add_argument("--retry-rate-limits", action="store_true",
                        help="Honor short provider cooldowns and retry a fictional case up to three times.")
    parser.add_argument("--audio-dir", type=Path, help="Optional fictional WAV recordings named 01.wav, 02.wav, and so on, in case order.")
    args = parser.parse_args()
    cases = DEV if args.split == "dev" else HOLDOUT
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        cases = cases[:args.limit]
    # Disable the optional remote written-number fallback regardless of the local secrets.
    with patch.object(ai_extractor, "_written_amount", return_value=None):
        print("Local parser")
        evaluate(cases, verbose=args.verbose)
    if args.model:
        key = groq_key()
        if not key:
            parser.error("Set GROQ_API_KEY to compare the model with the local parser.")
        print(f"Groq model: {args.model}")
        last_request = [0.0]

        cache = {}

        def get_proposal(turns):
            key_text = json.dumps(turns, ensure_ascii=False)
            if key_text not in cache:
                sleep(max(0, args.request_interval - (monotonic() - last_request[0])))
                last_request[0] = monotonic()
                for attempt in range(4):
                    try:
                        cache[key_text] = request_proposal(turns, key, model=args.model, today=date.today())
                        break
                    except UnderstandingError as exc:
                        delay = getattr(exc, "retry_after", None)
                        if not args.retry_rate_limits or delay is None or delay > 120 or attempt == 3:
                            cache[key_text] = exc
                            break
                        sleep(max(1, delay + 1))
                        last_request[0] = monotonic()
            proposal = cache[key_text]
            if isinstance(proposal, Exception):
                raise proposal
            return proposal

        def raw_parser(turns, pending=None):
            proposal = get_proposal(turns)
            if proposal["question"]:
                return {"clarification": {"kind": proposal["question_kind"], "question": proposal["question"]}}
            rows, reminders = [], []
            indexes = {}
            for i, entry in enumerate(proposal["entries"]):
                if entry["kind"] in ("credit", "debit"):
                    indexes[i] = len(rows)
                    rows.append(dict(amount=entry["amount"], category=entry["category"],
                                     transaction_type=entry["kind"], date=entry["day"] or day(0)))
            for entry in proposal["entries"]:
                if entry["kind"] in ("collect", "pay"):
                    parent = entry["expense_index"]
                    reminders.append(dict(amount=entry["amount"], direction=entry["kind"], person=entry["person"],
                                          due_date=entry["day"], transaction_index=None if parent == -1 else indexes.get(parent, -2)))
            return {"transactions": rows, "reminders": reminders}

        def model_parser(turns, pending=None):
            try:
                return validate_proposal(get_proposal(turns), turns, today=date.today())
            except (ValueError, KeyError, IndexError, TypeError, ArithmeticError) as exc:
                if isinstance(exc, UnderstandingError):
                    raise
                raise UnderstandingError("Invalid model draft") from None

        print("Structured model before validation")
        evaluate(cases, raw_parser, verbose=args.verbose)
        print("Same model proposals after validation")
        evaluate(cases, model_parser, verbose=args.verbose)
    if args.audio_dir:
        voice_key = gnani_api_key()
        if not voice_key:
            parser.error("Set GNANI_API_KEY to run the audio comparison.")
        heard = []
        for index, case in enumerate(cases, start=1):
            path = args.audio_dir / f"{index:02d}.wav"
            try:
                transcript = transcribe_recording(path.read_bytes(), voice_key)
            except (OSError, TranscriptionError) as exc:
                parser.error(f"{path.name}: {exc}")
            heard.append(replace(case, text=transcript))
            if args.verbose:
                print(f"{case.name}\n  intended: {case.text}\n  heard:    {transcript}")
        with patch.object(ai_extractor, "_written_amount", return_value=None):
            print("Gnani transcripts → local parser")
            evaluate(heard, verbose=args.verbose)
        if args.model:
            print(f"Gnani transcripts → {args.model}")
            evaluate(heard, model_parser, verbose=args.verbose)
