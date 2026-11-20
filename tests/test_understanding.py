from datetime import date
import unittest

from draft_edits import apply_preferences, edit_amount, teach_command
from understanding import UnderstandingError, validate_proposal


def proposal(source, *, kind="debit", amount=3000, day=""):
    return {"question": "", "question_kind": "", "entries": [
        {"kind": kind, "amount": amount, "category": "Entertainment", "day": day,
         "note": "Movie", "person": "", "source": source},
    ]}


def split_proposal():
    result = proposal("I paid 3000 for the movie")
    result["entries"].append({
        "kind": "collect", "amount": 1500, "category": "", "day": "", "note": "Movie split",
        "person": "Aditya", "source": "Aditya owes me 1500", "expense_index": 0,
    })
    return result


class UnderstandingTests(unittest.TestCase):
    def test_connected_model_payments_share_the_spoken_date(self):
        first = "Yesterday I paid 3000 for the movie"
        second = "paid 80 for tea"
        data = proposal(first, day="2026-11-19")
        data["entries"] += proposal(second, amount=80)["entries"]
        result = validate_proposal(data, [{"role": "user", "content": first + " and " + second}],
                                   today=date(2026, 11, 20))
        self.assertEqual([r["date"] for r in result["transactions"]], ["2026-11-19"] * 2)

    def test_cropped_quotes_cannot_hide_pending_payments_or_corrections(self):
        cases = (
            ("I owe Aditya 3000", "3000", "debit"),
            ("I did not pay 3000 for the movie", "pay 3000 for the movie", "debit"),
            ("I received 3000", "3000", "debit"),
            ("I paid 3000 for rent. No, 2800.", "I paid 3000 for rent", "debit"),
            ("I owe Aditya 3000", "3000", "collect"),
            ("I owe 3000 to Aditya", "3000", "debit"),
        )
        for message, quote, kind in cases:
            with self.subTest(message=message, quote=quote), self.assertRaises(UnderstandingError):
                validate_proposal(proposal(quote, kind=kind), [{"role": "user", "content": message}], today=date.today())

    def test_hindi_name_continuation_supports_a_receivable(self):
        message = "350 मुझे लेने हैं। आदित्य से।"
        result = proposal("350 मुझे लेने हैं। आदित्य से।", kind="collect", amount=350)
        result["entries"][0]["person"] = "आदित्य"
        result = validate_proposal(result, [{"role": "user", "content": message}], today=date.today())
        self.assertEqual(result["reminders"][0]["direction"], "collect")

    def test_model_can_quote_a_full_loan_and_its_repayment_promise(self):
        source = "2000 आदित्य को उधार दिया। तो वो 2000 मेरे को वो वापस देगा?"
        data = proposal(source, amount=2000)
        data["entries"].append({
            **data["entries"][0], "kind": "collect", "person": "आदित्य", "expense_index": 0,
        })
        result = validate_proposal(data, [{"role": "user", "content": source}], today=date.today())
        self.assertEqual(result["transactions"][0]["amount"], 2000)
        self.assertEqual(result["reminders"][0]["transaction_index"], 0)

    def test_overlapping_quotes_cannot_duplicate_an_expense(self):
        message = "I paid 3000 for the movie"
        result = proposal(message)
        result["entries"].append({**result["entries"][0], "source": "paid 3000 for the movie"})
        with self.assertRaises(UnderstandingError):
            validate_proposal(result, [{"role": "user", "content": message}], today=date.today())

    def test_counterparty_cannot_be_borrowed_from_an_unrelated_entry(self):
        message = "Aditya owes me 1500 and Rahul owes me 500"
        result = proposal("Aditya owes me 1500", kind="collect", amount=1500)
        result["entries"][0]["person"] = "Rahul"
        with self.assertRaises(UnderstandingError):
            validate_proposal(result, [{"role": "user", "content": message}], today=date.today())

    def test_identical_expenses_in_distinct_statements_remain_valid(self):
        message = "I paid 3000 for rent; I paid 3000 for the movie"
        result = proposal("I paid 3000 for rent")
        result["entries"].append({**result["entries"][0], "source": "I paid 3000 for the movie"})
        self.assertEqual(len(validate_proposal(result, [{"role": "user", "content": message}],
                                              today=date.today())["transactions"]), 2)

    def test_correction_in_next_turn_invalidates_old_amount_and_keeps_other_items(self):
        turns = [
            {"role": "user", "content": "I paid 3000 for the movie and paid 500 for petrol"},
            {"role": "assistant", "content": "Did you pay 3000 for the movie?"},
            {"role": "user", "content": "No, 2800."},
        ]
        with self.assertRaises(UnderstandingError):
            validate_proposal(proposal("I paid 3000 for the movie"), turns, today=date.today())
        result = proposal("No, 2800.", amount=2800)
        result["entries"].append({**result["entries"][0], "amount": 500, "source": "paid 500 for petrol"})
        validated = validate_proposal(result, turns, today=date.today())
        self.assertEqual([row["amount"] for row in validated["transactions"]], [2800, 500])

    def test_bare_reply_can_correct_the_asked_about_amount(self):
        turns = [
            {"role": "user", "content": "I paid 3000 for the movie"},
            {"role": "assistant", "content": "How much did you pay for the movie?"},
            {"role": "user", "content": "2800"},
        ]
        with self.assertRaises(UnderstandingError):
            validate_proposal(proposal("I paid 3000 for the movie"), turns, today=date.today())
        result = validate_proposal(proposal("2800", amount=2800), turns, today=date.today())
        self.assertEqual(result["transactions"][0]["amount"], 2800)

    def test_model_split_stays_linked_during_expense_and_repayment_edits(self):
        turns = [{"role": "user", "content": "I paid 3000 for the movie and Aditya owes me 1500"}]
        draft = validate_proposal(split_proposal(), turns, today=date.today())
        self.assertEqual(draft["reminders"][0]["transaction_index"], 0)
        with self.assertRaises(ValueError):
            edit_amount(draft, "transaction", 0, "1000")
        with self.assertRaises(ValueError):
            edit_amount(draft, "reminder", 0, "3100")
        revised = edit_amount(draft, "transaction", 0, "2800")
        self.assertEqual(revised["transactions"][0]["amount"], 2800)
        self.assertEqual(revised["reminders"][0]["amount"], 1500)
        self.assertEqual(draft["transactions"][0]["amount"], 3000)

    def test_split_total_includes_every_counterparty(self):
        result = split_proposal()
        result["entries"].append({
            **result["entries"][1], "amount": 1600, "person": "Rahul", "source": "Rahul owes me 1600",
        })
        turns = [{"role": "user", "content": "I paid 3000 for the movie and Aditya owes me 1500 and Rahul owes me 1600"}]
        with self.assertRaises(UnderstandingError):
            validate_proposal(result, turns, today=date.today())

    def test_validation_blocks_pending_payments_wrong_direction_and_unsupported_amounts(self):
        for source, kind, amount in (
            ("450 देने हैं", "debit", 450),
            ("I owe Aditya 3000", "debit", 3000),
            ("I did not pay 3000 for the movie", "debit", 3000),
            ("I received 3000", "debit", 3000),
            ("I paid 3000 for the movie", "debit", 3100),
            ("I paid 3000 or 3100", "debit", 3100),
            ("I paid 3000 no 2800 for the movie", "debit", 3000),
        ):
            with self.subTest(source=source, amount=amount), self.assertRaises(UnderstandingError):
                validate_proposal(proposal(source, kind=kind, amount=amount),
                                  [{"role": "user", "content": source}], today=date(2026, 11, 14))

    def test_correction_changes_only_the_selected_expense(self):
        source = "I paid 3000 for the movie"
        draft = validate_proposal(proposal(source), [{"role": "user", "content": source}], today=date(2026, 11, 14))
        draft["reminders"].append({"direction": "collect", "person": "Aditya", "amount": 1500})
        revised = edit_amount(draft, "transaction", 0, "Change the movie to 2800. Keep the 1500 Aditya owes me.")
        self.assertEqual(revised["transactions"][0]["amount"], 2800)
        self.assertEqual(revised["transactions"][0]["source"], source)
        self.assertEqual(revised["reminders"], draft["reminders"])
        self.assertEqual(draft["transactions"][0]["amount"], 3000)

    def test_taught_category_changes_only_the_matching_category(self):
        phrase, category = teach_command("When I say ‘movie’, put it under Home")
        row = {"transaction_type": "debit", "amount": 3000, "source": "paid 3000 for the movie",
               "note": "Movie", "category": "Entertainment"}
        apply_preferences(row, {phrase: category})
        self.assertEqual(row["category"], "Home & Maintenance")
        self.assertEqual((row["transaction_type"], row["amount"]), ("debit", 3000))
