import os
import io
import shutil
import sqlite3
import tempfile
import unittest
import wave
from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd

import ai_extractor
import dashboard_utils
import db
import voice_input


class FinanceFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="expense-tracker-tests-")
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir, "expenses.db")
        db.init_db()

    def test_spoken_movie_repayment_and_salary_deduction(self):
        purchase = ai_extractor.extract_expense("I paid 3000 for movie tickets. Aditya will return 1500.")
        db.save_chat_entries([purchase], [])
        message = ("आदित्य has returned me the 1500 he gave, and now I paid. 3000, no, 4000 for the rent "
                   "and 2000 for the groceries and food. And I received 10,000 as my salary, "
                   "in which 500 was deducted. Due to tax, and 500 is for transport.")
        pending = ai_extractor.extract_expense(message)["clarification"]
        self.assertEqual(pending["kind"], "net_salary")
        self.assertIn("clarification", ai_extractor.resolve_clarification(pending, "500 tax"))
        rows = ai_extractor.resolve_clarification(pending, "9500")["transactions"]
        self.assertEqual([(r["amount"], r["transaction_type"]) for r in rows],
                         [(1500, "credit"), (4000, "debit"), (2000, "debit"), (9500, "credit"), (500, "debit")])
        ids, _ = db.save_chat_entries(rows, [])
        self.assertFalse(db.get_repayments())
        db.undo_chat_entries(ids, [])
        self.assertEqual(len(db.get_repayments()), 1)

    def test_paying_someone_back_settles_only_payable(self):
        for direction in ("collect", "pay"):
            db.add_repayment(direction, "Aditya", 1500, "Movie")
        payment = ai_extractor.extract_expense("I returned 1500 to Aditya")
        self.assertEqual(payment["transaction_type"], "debit")
        db.save_chat_entries([payment], [])
        self.assertEqual([row["direction"] for row in db.get_repayments()], ["collect"])

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_named_promise_after_movie_payment(self):
        for separator in (". ", " and "):
            message = "I paid ₹3,000 for movie tickets" + separator + "Aditya will return ₹1,500"
            result = ai_extractor.extract_expense(message)
            self.assertEqual((result["amount"], result["transaction_type"], result["category"]),
                             (3000, "debit", "Entertainment"))
            self.assertEqual(result["repayment"], {"person": "Aditya", "amount": 1500})
        with patch.object(db, "_database_path", return_value=db.DB_PATH):
            db.init_db()
            db.save_chat_entries([result], [])
            self.assertEqual(len(db.get_all_expenses_rows()), 1)
            reminder, = db.get_repayments()
        self.assertEqual((reminder["direction"], reminder["person"], reminder["amount"]),
                         ("collect", "Aditya", 1500))

    def test_movie_payment_and_personal_obligation(self):
        for wording in ("I owe Aditya 1500", "I have to give 1500 to Aditya",
                        "I have to return 1500 to Aditya"):
            result = ai_extractor.extract_expense("I paid 3000 for movie tickets. " + wording)
            payment, = result["transactions"]
            reminder, = result["reminders"]
            self.assertEqual((payment["transaction_type"], payment["amount"]), ("debit", 3000))
            self.assertEqual((reminder["direction"], reminder["amount"], reminder["person"]),
                             ("pay", 1500, "Aditya"))

    def test_connected_dates_and_cancelled_payments(self):
        parsed = ai_extractor.extract_expense(
            "Yesterday I paid 500 for food and received 1000 for work and paid 90 today for tea")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.assertEqual([r["date"] for r in parsed["transactions"]],
                         [yesterday, yesterday, date.today().isoformat()])
        for message in ("paid 200 for lunch and did not pay 400 for shoes",
                        "did not pay 400 for shoes, but paid 200 for lunch"):
            self.assertEqual(ai_extractor.extract_expense(message)["amount"], 200)
        self.assertIn("error", ai_extractor.extract_expense("paid 400 for shoes; card declined"))

    def test_duplicate_reminders_and_settled_parents(self):
        reminder = dict(direction="collect", person="Aditya", amount=350, note="")
        db.save_chat_entries([], [reminder], check_duplicates=True)
        with self.assertRaises(db.DuplicateExpense):
            db.save_chat_entries([{"amount": 90}], [reminder], check_duplicates=True)
        self.assertEqual(len(db.get_repayments()), 1)
        self.assertFalse(db.get_all_expenses_rows())
        parent = db.save_expense({"amount": 3000, "repayment": {"person": "Rahul", "amount": 1500}})
        db.settle_repayment(next(r["id"] for r in db.get_repayments() if r["expense_id"] == parent))
        with self.assertRaisesRegex(ValueError, "recorded repayment"):
            db.delete_expense(parent)
        self.assertEqual(len(db.get_all_expenses_rows()), 2)

    def test_persistent_monthly_budget_reset_roundtrip(self):
        db.set_monthly_budget("2026-10", "Transport", 500)
        db.set_monthly_budget("2026-11", "Transport", 750)
        self.assertEqual(db.monthly_budgets("2026-10"), {"Transport": 500})
        snapshot = db.reset_ledger()
        self.assertEqual(db.monthly_budgets("2026-10"), {})
        db.restore_ledger(snapshot)
        self.assertEqual(db.monthly_budgets("2026-11"), {"Transport": 750})
        self.assertIn("Limit reached", dashboard_utils.budget_progress(750, 750)["status"])

    def test_gnani_movie_transcript_preserves_entertainment_category(self):
        text = voice_input.normalize_voice_transcript("मैंने मूवी के लिए 3,000 रुपये पे किए।")
        entry = ai_extractor.extract_expense(text, allow_remote_amount=False)
        self.assertEqual((entry["amount"], entry["category"]), (3000, "Entertainment"))

    def test_rule_engine_parses_merchant_and_category_without_ai(self):
        result = ai_extractor.extract_expense("uber 240 today")

        self.assertNotIn("error", result)
        self.assertEqual(result["transaction_type"], "debit")
        self.assertEqual(result["amount"], 240.0)
        self.assertEqual(result["category"], "Transport")
        self.assertEqual(result["date"], str(date.today()))
        self.assertIn("Uber", result["note"])

    def test_future_dates_require_confirmation(self):
        future_text = "paid 500 tomorrow groceries"
        result = ai_extractor.extract_expense(future_text)
        self.assertIn("error", result)
        self.assertIn("Future dates require explicit confirmation", result["error"])

        confirmed = ai_extractor.extract_expense(future_text + " confirm future date")
        self.assertNotIn("error", confirmed)
        self.assertEqual(confirmed["date"], str(date.today() + timedelta(days=1)))

    def test_amounts_dates_and_categories_stay_with_their_transaction(self):
        result = ai_extractor.extract_expense(
            "received 20k salary on 2025-04-21 and paid ₹750.50 for the 2 train tickets yesterday"
        )
        self.assertEqual(
            [(row["amount"], row["transaction_type"], row["date"], row["category"])
             for row in result["transactions"]],
            [
                (20000, "credit", "2025-04-21", "Salary"),
                (750.50, "debit", str(date.today() - timedelta(days=1)), "Transport"),
            ],
        )

    def test_split_follow_up_keeps_the_rest_of_the_batch(self):
        result = ai_extractor.extract_expense(
            "paid 500 for dinner, split with Rahul and paid 240 for Uber"
        )
        self.assertEqual(result["clarification"]["kind"], "amount")
        result = ai_extractor.resolve_clarification(result["clarification"], "₹250.50")
        self.assertEqual([row["amount"] for row in result["transactions"]], [250.50, 240])
        self.assertEqual(result["transactions"][0]["category"], "Food & Dining")

    def test_failed_payment_and_invalid_date_do_not_produce_transactions(self):
        failed = ai_extractor.extract_expense("did not pay ₹250 for dinner; card declined")
        self.assertIn("error", failed)
        invalid = ai_extractor.extract_expense("paid ₹50 for food on 2026-02-30")
        self.assertEqual(invalid["clarification"]["kind"], "date")
        self.assertNotIn("amount", invalid)

    def test_future_confirmation_survives_an_invalid_reply(self):
        result = ai_extractor.extract_expense("paid 500 tomorrow; never confirm future date")
        self.assertEqual(result["clarification"]["kind"], "future")
        result = ai_extractor.resolve_clarification(result["clarification"], "maybe")
        result = ai_extractor.resolve_clarification(result["clarification"], "yes")
        self.assertEqual(result["date"], str(date.today() + timedelta(days=1)))

    def test_batch_rolls_back_when_second_insert_fails(self):
        conn = db.get_conn()
        try:
            conn.execute("""
                CREATE TRIGGER reject_second BEFORE INSERT ON expenses
                WHEN NEW.amount = 222
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)
        finally:
            conn.close()
        with self.assertRaises(sqlite3.IntegrityError):
            db.save_expenses([{"amount": 111}, {"amount": 222}])
        self.assertEqual(db.get_all_expenses_rows(), [])

    def test_duplicate_rolls_back_batch_and_reset_never_reuses_id(self):
        transaction = {"amount": 250.50, "category": "Transport", "note": "Uber"}
        original = db.save_expense(transaction)
        with self.assertRaises(db.DuplicateExpense):
            db.save_expenses([{"amount": 100}, transaction], check_duplicates=True)
        self.assertEqual([row["id"] for row in db.get_all_expenses_rows()], [original])
        snapshot = db.delete_all_expenses()
        replacement = db.save_expense({"amount": 75})
        db.delete_expenses_by_ids([original])
        self.assertGreater(replacement, original)
        db.insert_expense_rows(snapshot)
        self.assertEqual([row["id"] for row in db.get_all_expenses_rows()], [original, replacement])

    def test_db_save_and_reset_roundtrip(self):
        txn_id = db.save_expense({
            "amount": 123.0,
            "category": "Groceries",
            "transaction_type": "debit",
            "date": str(date.today()),
            "note": "Milk",
            "raw_input": "paid 123 groceries",
        })

        saved = db.get_expense_by_id(txn_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["amount"], 123.0)
        self.assertEqual(saved["category"], "Groceries")

        rows_before = db.get_all_expenses_rows()
        self.assertEqual(len(rows_before), 1)

        db.delete_all_expenses()
        rows_after = db.get_all_expenses_rows()
        self.assertEqual(rows_after, [])

    def test_split_collection_posts_once_and_undo_reopens_the_reminder(self):
        split = ai_extractor.extract_expense("I paid ₹3,000 for dinner and Rahul owes me ₹1,500")
        self.assertEqual(split["amount"], 3000)
        original = db.save_expense(split)
        reminder, = db.get_repayments()
        self.assertEqual((reminder["expense_id"], reminder["person"], reminder["amount"]), (original, "Rahul", 1500))
        self.assertEqual(db.get_summary_stats()["total_credit"], 0)

        settlement = db.settle_repayment(reminder["id"])
        self.assertIsNone(db.settle_repayment(reminder["id"]))
        self.assertEqual(db.get_repayments(), [])
        self.assertEqual(db.get_summary_stats()["total_credit"], 1500)
        db.delete_expense(settlement)
        self.assertEqual(db.get_repayments(), [reminder])
        self.assertEqual(db.get_summary_stats()["total_credit"], 0)

        snapshot = db.delete_all_expenses()
        self.assertEqual(db.get_repayments(), [])
        db.insert_expense_rows(snapshot)
        self.assertEqual(db.get_repayments(), [reminder])
        db.delete_expenses_by_ids([original])
        self.assertEqual(db.get_repayments(), [])

    def test_money_i_owe_only_counts_when_paid(self):
        spoken = voice_input.normalize_voice_transcript("मुझे आदित्य को ५०० रुपये देने हैं।")
        reminder = ai_extractor.extract_expense(spoken)["reminder"]
        self.assertEqual((reminder["person"], reminder["direction"], reminder["amount"]), ("आदित्य", "pay", 500))
        _, (reminder_id,) = db.save_chat_entries([], [reminder])
        due = str(date.today() + timedelta(days=2))
        db.update_repayment(reminder_id, "आदित्य", due)
        self.assertEqual(db.get_repayments()[0]["due_date"], due)
        self.assertEqual(db.get_summary_stats()["total_debit"], 0)
        settlement = db.settle_repayment(reminder_id)
        self.assertEqual(db.get_expense_by_id(settlement)["transaction_type"], "debit")
        self.assertEqual(db.get_summary_stats()["total_debit"], 500)

    def test_mixed_chat_save_and_undo_include_unpaid_reminders(self):
        result = ai_extractor.extract_expense(
            "I paid 3000 for a movie and I need to take 1500 back from Aditya; I owe Rahul 300"
        )
        ids, reminder_ids = db.save_chat_entries(result["transactions"], result["reminders"])
        self.assertEqual(db.get_summary_stats()["total_debit"], 3000)
        self.assertEqual(db.get_summary_stats()["total_credit"], 0)
        self.assertCountEqual(
            [(row["direction"], row["person"], row["amount"]) for row in db.get_repayments()],
            [("collect", "Aditya", 1500), ("pay", "Rahul", 300)],
        )
        db.undo_chat_entries(ids, reminder_ids)
        self.assertEqual(db.get_all_expenses_rows(), [])
        self.assertEqual(db.get_repayments(), [])
        with self.assertRaises(ValueError):
            db.save_chat_entries(result["transactions"], [{**result["reminders"][0], "amount": -5}])
        self.assertEqual(db.get_all_expenses_rows(), [])
        self.assertEqual(db.get_repayments(), [])

    def test_model_split_links_survive_save_settlement_delete_and_undo(self):
        transaction = {"amount": 3000, "category": "Entertainment", "note": "Movie"}
        reminder = {"amount": 1500, "direction": "collect", "person": "Aditya",
                    "note": "Movie split", "transaction_index": 0}
        ids, _ = db.save_chat_entries([transaction], [reminder])
        saved, = db.get_repayments()
        self.assertEqual(saved["expense_id"], ids[0])
        settlement = db.settle_repayment(saved["id"])
        self.assertEqual(db.get_summary_stats()["total_credit"], 1500)
        self.assertIsNone(db.settle_repayment(saved["id"]))
        db.delete_expense(settlement)
        self.assertEqual(db.get_repayments(), [saved])
        deleted = db.delete_expense(ids[0])
        self.assertEqual(db.get_repayments(), [])
        db.insert_expense_row(deleted)
        self.assertEqual(db.get_repayments(), [saved])
        snapshot = db.delete_all_expenses()
        self.assertEqual(db.get_repayments(), [])
        db.insert_expense_rows(snapshot)
        self.assertEqual(db.get_repayments(), [saved])

    def test_database_rejects_impossible_model_splits_before_any_write(self):
        transaction = {"amount": 3000, "note": "Movie"}
        reminder = {"amount": 1500, "direction": "collect", "person": "Aditya",
                    "note": "Split", "transaction_index": 0}
        invalid = (
            [dict(reminder, transaction_index=1)],
            [dict(reminder, direction="pay")],
            [dict(reminder, amount=3001)],
            [reminder, dict(reminder, person="Rahul", amount=1600)],
        )
        for reminders in invalid:
            with self.subTest(reminders=reminders), self.assertRaises(ValueError):
                db.save_chat_entries([transaction], reminders)
            self.assertEqual(db.get_all_expenses_rows(), [])
            self.assertEqual(db.get_repayments(), [])

    def test_moving_wrong_expense_to_reminder_is_atomic_and_reversible(self):
        expense_id = db.save_expense({"amount": 350, "note": "I owe 350 to Aditya"})
        original = db.get_expense_by_id(expense_id)
        payload = db.move_expense_to_repayments(expense_id, "collect", "Aditya")
        self.assertEqual(db.get_summary_stats()["total_debit"], 0)
        reminder, = db.get_repayments()
        self.assertEqual((reminder["amount"], reminder["direction"], reminder["person"]), (350, "collect", "Aditya"))
        with self.assertRaises(ValueError):
            db.move_expense_to_repayments(expense_id, "collect", "Aditya")
        db.undo_move_to_repayments(payload)
        self.assertEqual(db.get_repayments(), [])
        self.assertEqual(db.get_expense_by_id(expense_id), original)

    def test_dashboard_transforms(self):
        rows = pd.DataFrame([
            {"date": pd.Timestamp(date.today()), "transaction_type": "credit", "amount": 5000, "category": "Salary", "note": "Pay"},
            {"date": pd.Timestamp(date.today()), "transaction_type": "debit", "amount": 1200, "category": "Groceries", "note": "Milk"},
            {"date": pd.Timestamp(date.today().replace(day=1) - timedelta(days=2)), "transaction_type": "credit", "amount": 3000, "category": "Freelance", "note": "Client"},
            {"date": pd.Timestamp(date.today().replace(day=1) - timedelta(days=2)), "transaction_type": "debit", "amount": 700, "category": "Transport", "note": "Uber"},
        ])

        comparison = dashboard_utils.calculate_period_comparison(rows, today=date.today())
        self.assertGreater(comparison["this_month"]["income"], comparison["last_month"]["income"])
        self.assertIn(comparison["income_arrow"], ["📈", "📉"])

        export_frame = dashboard_utils.prepare_export_frame(rows)
        self.assertEqual(list(export_frame.columns), ["date", "transaction_type", "category", "amount", "note"])
        self.assertIsInstance(export_frame.iloc[0]["date"], str)

        budget = dashboard_utils.budget_progress(850, 1000)
        self.assertEqual(budget["status"], "⚠️ Near limit")
        self.assertAlmostEqual(budget["percent"], 85.0, places=1)


class VoiceInputTests(unittest.TestCase):
    def test_hindi_loan_recording_counts_repeated_principal_once_and_tracks_collection(self):
        transcript = (
            "कल 10000 रुपये मिले, उसमें से 3500 नहीं, 4000 rent दिया। और 2000 खाने के लिए दिया, "
            "और 2000 आदित्य को उधार दिया। तो वो 2000 मेरे को वो वापस देगा?"
        )
        result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
        self.assertNotIn("clarification", result)
        self.assertEqual(
            [(row["amount"], row["transaction_type"]) for row in result["transactions"]],
            [(10000, "credit"), (4000, "debit"), (2000, "debit"), (2000, "debit")],
        )
        self.assertEqual(result["transactions"][-1]["repayment"], {"amount": 2000, "person": "आदित्य"})

    def test_collect_reply_resolves_a_legacy_loan_amount_follow_up(self):
        pending = ai_extractor.extract_expense("paid 2000 or 2500")["clarification"]
        pending["context"]["clauses"][0] = voice_input.normalize_voice_transcript(
            "2000 आदित्य को उधार दिया। तो वो 2000 मेरे को वो वापस देगा?"
        )
        result = ai_extractor.resolve_clarification(
            pending, voice_input.normalize_voice_transcript("2000 आदित्य से लेने हैं।"),
        )
        self.assertNotIn("clarification", result)
        self.assertEqual((result["amount"], result["transaction_type"]), (2000, "debit"))
        self.assertEqual(result["repayment"], {"amount": 2000, "person": "आदित्य"})

    def test_loan_phrasings_keep_payment_and_repayment_separate(self):
        for transcript in (
            "I lent 2000 to Aditya. He will return 2000.",
            "I loaned Aditya 2000",
            "maine Aditya ko 2000 udhaar diya aur woh 2000 wapas dega",
            "2000 आदित्य को उधार दिया",
        ):
            with self.subTest(transcript=transcript):
                result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
                self.assertNotIn("clarification", result)
                self.assertEqual((result["amount"], result["transaction_type"]), (2000, "debit"))
                self.assertEqual(result["repayment"]["amount"], 2000)
        self.assertIn("error", ai_extractor.extract_expense("I did not lend 2000 to Aditya"))

    def test_owe_amount_before_or_after_name_never_becomes_spending(self):
        for transcript, direction, person in (
            ("I owe 350 to Aditya", "pay", "Aditya"),
            ("I owe Aditya 350", "pay", "Aditya"),
            ("350 मुझे देने हैं आदित्य को", "pay", "आदित्य"),
            ("350 मुझे लेने हैं। आदित्य से।", "collect", "आदित्य"),
            ("मुझे आदित्य से 350 लेने हैं", "collect", "आदित्य"),
            ("mujhe Aditya se 350 lene hain", "collect", "Aditya"),
            ("mujhe 350 Aditya ko dene hain", "pay", "Aditya"),
            ("I have to take 350 from Aditya", "collect", "Aditya"),
        ):
            with self.subTest(transcript=transcript):
                result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
                self.assertIn("reminder", result)
                self.assertEqual(
                    (result["reminder"]["direction"], result["reminder"]["person"], result["reminder"]["amount"]),
                    (direction, person, 350),
                )

    def test_original_chat_keeps_food_income_and_receivable_separate(self):
        transcript = (
            "कल 500 दिए, चाय वाले पे उधार बाकी था और। 1000 मिले जिसका काम किया, "
            "और 350 मुझे लेने हैं। आदित्य से, क्योंकि उसने लिए थे message।"
        )
        result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
        self.assertEqual(
            [(row["amount"], row["transaction_type"]) for row in result["transactions"]],
            [(500, "debit"), (1000, "credit")],
        )
        reminder, = result["reminders"]
        self.assertEqual((reminder["direction"], reminder["amount"], reminder["person"]), ("collect", 350, "आदित्य"))
        self.assertEqual(result["transactions"][0]["date"], str(date.today() - timedelta(days=1)))

    def test_legacy_details_reply_can_change_expense_to_debt_and_keep_the_person(self):
        result = ai_extractor.extract_expense("350")
        pending = result["clarification"]
        pending["context"]["clauses"][0] = "350 मुझे लेने हैं. आदित्य से."
        result = ai_extractor.resolve_clarification(
            pending, voice_input.normalize_voice_transcript("और 350 मुझे लेने हैं, IO 350।"),
        )
        self.assertIn("reminder", result)
        self.assertEqual(result["reminder"]["direction"], "collect")
        self.assertEqual(result["reminder"]["person"], "आदित्य")
        self.assertEqual(result["reminder"]["amount"], 350)

    def test_conflicting_debt_directions_require_a_targeted_question(self):
        result = ai_extractor.extract_expense("I owe 350 to Aditya, मुझे लेने हैं")
        self.assertEqual(result["clarification"]["kind"], "direction")
        result = ai_extractor.resolve_clarification(result["clarification"], "I need to collect")
        self.assertEqual(result["reminder"]["direction"], "collect")
        self.assertEqual(result["reminder"]["person"], "Aditya")

    def test_balance_and_savings_do_not_hide_a_separate_food_expense(self):
        for transcript in (
            "3000 मिले, उसमें से 2000 नई 1900 दोस्त को दिए और। "
            "बाकी के 1100 में से 500 का खाना खाया और बाकी की save कर ली।",
            "3000 mile, usme se 2000 nahi 1900 dost ko diye aur "
            "baki ke 1100 mein se 500 ka khana khaya aur baki save kar li",
            "I received ₹3,000. I gave a friend ₹2,000, no, ₹1,900. "
            "Out of the remaining ₹1,100 I spent ₹500 on food and saved the rest.",
            "3000 मिले, उसमें से 2000 नहीं 1900 दोस्त को दिए और "
            "बचे हुए 1100 में से 500 खाने पर खर्च किए, बाकी 600 बचा लिए।",
        ):
            with self.subTest(transcript=transcript):
                result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
                self.assertNotIn("clarification", result)
                self.assertEqual(
                    [(row["amount"], row["transaction_type"], row["category"]) for row in result["transactions"]],
                    [(3000, "credit", "Other Income"), (1900, "debit", "Other"), (500, "debit", "Food & Dining")],
                )

    def test_screenshot_reply_resolves_movie_payment_and_preserves_unpaid_debt(self):
        transcript = (
            "10000 मिले, 5000 नहीं, 4000 rent था। 3000 movie कह रहे हैं, जिसमें से 1500 लेने हैं मेरे को और। "
            "और 500 का transportation में लगे, और 300 मेरे को देने हैं आदित्य को।"
        )
        pending = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))["clarification"]
        self.assertIn("Did you pay ₹3,000 for the movie?", pending["question"])
        self.assertIn("₹1,500", pending["question"])
        self.assertEqual(pending["ready_reminders"][0]["direction"], "pay")
        result = ai_extractor.resolve_clarification(
            pending, "i paid 3000 in which i have to take 1500 back from aditya",
        )
        self.assertEqual(
            [(row["amount"], row["transaction_type"], row["category"]) for row in result["transactions"]],
            [(10000, "credit", "Other Income"), (4000, "debit", "Home & Maintenance"),
             (3000, "debit", "Entertainment"), (500, "debit", "Transport")],
        )
        self.assertEqual(result["transactions"][2]["repayment"], {"person": "Aditya", "amount": 1500})
        reminder, = result["reminders"]
        self.assertEqual((reminder["direction"], reminder["person"], reminder["amount"]), ("pay", "आदित्य", 300))

    def test_to_give_follow_up_asks_for_a_payee_without_drafting_an_expense(self):
        pending = ai_extractor.extract_expense("300")["clarification"]
        pending = ai_extractor.resolve_clarification(pending, "it was to give")["clarification"]
        self.assertEqual(pending["question"], "Who do you still owe ₹300 to?")
        result = ai_extractor.resolve_clarification(pending, "to Aditya")
        self.assertEqual(result["reminder"]["person"], "Aditya")
        self.assertEqual(result["reminder"]["direction"], "pay")

    def test_long_hinglish_recording_keeps_each_item_and_asks_about_what_is_unclear(self):
        transcript = (
            "10000 मिले, उसमें से 5000 नहीं, 4000 गिराया गया। 3500 movie के लगे, उसमें से आधे आधे "
            "country होंगे, तो आधे आएंगे। तो आदित्य से लेने हैं, ये भी note करो। और और 500 trnasport लगा "
            "और। 300 आने का भाड़ा लगा।"
        )
        pending = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))["clarification"]
        self.assertIn("₹4,000", pending["question"])
        self.assertEqual([row["amount"] for row in pending["ready"]], [10000, 500, 300])
        retry = ai_extractor.resolve_clarification(pending, "10000")["clarification"]
        self.assertEqual(retry["question"], pending["question"])
        self.assertIn("reply_hint", retry)
        pending = ai_extractor.resolve_clarification(retry, "rent")["clarification"]
        self.assertIn("₹3,500", pending["question"])
        self.assertIn("movie", pending["question"])
        pending = ai_extractor.resolve_clarification(pending, "3500")["clarification"]
        self.assertEqual(pending["suggestion"], 1750)
        result = ai_extractor.resolve_clarification(pending, "1750")["transactions"]
        self.assertEqual(
            [(row["amount"], row["transaction_type"], row["category"]) for row in result],
            [(10000, "credit", "Other Income"), (4000, "debit", "Home & Maintenance"),
             (3500, "debit", "Entertainment"), (500, "debit", "Transport"), (300, "debit", "Transport")],
        )
        self.assertEqual(result[2]["repayment"], {"person": "आदित्य", "amount": 1750})

    def test_equal_split_suggests_half_without_recording_it_as_income(self):
        pending = ai_extractor.extract_expense("I paid ₹3,000 for dinner and split it in half with Rahul")["clarification"]
        self.assertEqual((pending["kind"], pending["suggestion"]), ("due", 1500))
        result = ai_extractor.resolve_clarification(pending, "1500")
        self.assertEqual((result["amount"], result["transaction_type"]), (3000, "debit"))
        self.assertEqual(result["repayment"], {"person": "Rahul", "amount": 1500})

    def test_spoken_corrections_replace_the_amount_and_keep_rent_outgoing(self):
        for text in (
            "Rent was 5,000. No, no, 4,000.",
            "I paid 5,000 for rent. No. 4,000.",
            "Maine kiraya 5000 diya, nahi nahi 4000.",
            "मैंने किराया ₹५००० दिया, नहीं नहीं ₹४०००।",
        ):
            with self.subTest(text=text):
                result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(text))
                self.assertEqual((result["amount"], result["transaction_type"], result["category"]),
                                 (4000, "debit", "Home & Maintenance"))

    def test_ambiguous_rent_does_not_absorb_income_or_money_set_aside(self):
        transcript = "10000 mile, 5000 4000 rent bhi diya aur. 3000 ki grocery लाया aur बाकी 2000 pocket money के लिए save करा."
        result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
        self.assertIn("rent", result["clarification"]["question"])
        self.assertNotIn("transactions", result)
        result = ai_extractor.resolve_clarification(result["clarification"], "No, 4,000 rupees.")
        self.assertEqual(
            [(row["amount"], row["transaction_type"], row["category"]) for row in result["transactions"]],
            [(10000, "credit", "Other Income"), (4000, "debit", "Home & Maintenance"), (3000, "debit", "Groceries")],
        )

    def test_gnani_returns_a_normalized_amount_transcript(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x00\x00")
        response = Mock(status_code=200)
        response.json.return_value = {"success": True, "transcript": "आज मेट्रो के लिए ₹६० दिए।"}
        with patch.object(voice_input.requests, "post", return_value=response) as post:
            transcript = voice_input.transcribe_recording(buffer.getvalue(), "test-key")
        self.assertEqual(post.call_args.kwargs["data"]["format"], "transcribe")
        result = ai_extractor.extract_expense(voice_input.normalize_voice_transcript(transcript))
        self.assertEqual((result["amount"], result["category"], result["date"]), (60, "Transport", str(date.today())))

    def test_spoken_follow_up_can_supply_amount_date_or_confirmation(self):
        split = ai_extractor.extract_expense("paid 500 for dinner, split with Rahul")
        reply = voice_input.normalize_voice_transcript("२५० रुपये।")
        self.assertEqual(ai_extractor.resolve_clarification(split["clarification"], reply)["amount"], 250)

        date_question = ai_extractor.extract_expense("paid 500 on 03/04 for dinner")
        reply = voice_input.normalize_voice_transcript("३ अप्रैल २०२५।")
        result = ai_extractor.resolve_clarification(date_question["clarification"], reply)
        self.assertEqual(result["date"], "2025-04-03")

        refund = ai_extractor.extract_expense("refund 350 from Amazon")
        reply = voice_input.normalize_voice_transcript("जी हाँ।")
        self.assertEqual(ai_extractor.resolve_clarification(refund["clarification"], reply)["transaction_type"], "credit")

    def test_spoken_negation_is_preserved(self):
        transcript = voice_input.normalize_voice_transcript("आज लंच के लिए ₹500 नहीं दिए।")
        self.assertIn("error", ai_extractor.extract_expense(transcript))


if __name__ == "__main__":
    unittest.main()
