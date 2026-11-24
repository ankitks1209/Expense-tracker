from datetime import date
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import db
from ai_extractor import _clauses, extract_expense
from understanding import validate_proposal
from voice_input import normalize_voice_transcript


class ChatUnderstandingTests(unittest.TestCase):
    def test_two_spoken_splits_reach_dashboard_with_person_and_purpose(self):
        transcript = ("I paid 3000 for the movie. Aditya will retain, Aditya will return me 1500 from it. "
                      "And I paid 500 for transport, in which 250 will return, Aditya.")
        with TemporaryDirectory() as temp, patch.object(db, "DB_PATH", str(Path(temp) / "ledger.sqlite3")), patch(
            "streamlit.secrets", {}
        ), patch.dict(os.environ, {"ENMA_LEDGER_PASSCODE": "", "ENMA_DEMO_MODE": "0"}):
            chat = AppTest.from_file("chat.py").run()
            chat.chat_input(key="chat_input").set_value(transcript).run()
            self.assertIsNone(chat.session_state.pending_clarification)
            chat.button(key="save_voice_draft").click().run()
            self.assertFalse(chat.exception)
            self.assertEqual(db.get_summary_stats()["net_balance"], -3500)
            dashboard = AppTest.from_file("dashboard.py").run()
            self.assertFalse(dashboard.exception)
            labels = [item.value for item in dashboard.text]
            for label in ("Aditya owes you ₹1,500", "Movie", "Aditya owes you ₹250", "Transport"):
                self.assertIn(label, labels)
            self.assertEqual(len({r["expense_id"] for r in db.get_repayments()}), 2)

    def test_pending_loan_reply_keeps_the_whole_batch_and_saves_one_receivable(self):
        transcript = (
            "कल 10000 रुपये मिले, उसमें से 3500 नहीं, 4000 rent दिया। और 2000 खाने के लिए दिया, "
            "और 2000 आदित्य को उधार दिया। तो वो 2000 मेरे को वो वापस देगा?"
        )
        pending = extract_expense("paid 2000 or 2500")["clarification"]
        pending["index"] = 3
        pending["context"]["clauses"] = _clauses(normalize_voice_transcript(transcript))
        pending["context"]["raw_input"] = transcript
        pending["original_message"] = transcript
        original_path = db.DB_PATH
        try:
            with TemporaryDirectory() as temp, patch("streamlit.secrets", {}), patch.dict(
                os.environ, {"ENMA_LEDGER_PASSCODE": ""}
            ):
                db.DB_PATH = str(Path(temp) / "ledger.sqlite3")
                app = AppTest.from_file("chat.py").run()
                app.session_state["pending_clarification"] = pending
                app.run()
                app.chat_input(key="chat_input").set_value("2000 आदित्य से लेने हैं।").run()
                self.assertFalse(app.exception)
                self.assertIsNone(app.session_state.pending_clarification)
                self.assertEqual(len(app.session_state.voice_draft["transactions"]), 4)
                self.assertEqual(db.get_all_expenses_rows(), [])
                app.button(key="save_voice_draft").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(db.get_summary_stats()["net_balance"], 2000)
                reminder, = db.get_repayments()
                self.assertEqual((reminder["person"], reminder["amount"]), ("आदित्य", 2000))
                self.assertIsNotNone(reminder["expense_id"])
                app.button(key="undo_last_action").click().run()
                self.assertEqual(db.get_all_expenses_rows(), [])
                self.assertEqual(db.get_repayments(), [])
        finally:
            db.DB_PATH = original_path

    def test_rejected_draft_then_corrected_split_saves_and_undoes_together(self):
        def model(turns, _key):
            expense = {
                "kind": "debit", "amount": 3000, "category": "Entertainment", "day": "",
                "person": "", "note": "Movie", "source": "I paid 3000 for the movie",
                "expense_index": -1,
            }
            if "owe Aditya" in turns[-1]["content"]:
                entries = [{**expense, "source": "3000"}]
            else:
                entries = [
                    expense,
                    {"kind": "collect", "amount": 1500, "category": "", "day": "", "person": "Aditya",
                     "note": "Movie split", "source": "Aditya owes me 1500", "expense_index": 0},
                ]
            data = {"entries": entries, "question": "", "question_kind": ""}
            return validate_proposal(data, turns, today=date.today())

        original_path = db.DB_PATH
        try:
            with TemporaryDirectory() as temp, patch("streamlit.secrets", {}), patch.dict(
                os.environ, {"ENMA_LEDGER_PASSCODE": ""}
            ), patch("understanding.ask_model", side_effect=model):
                db.DB_PATH = str(Path(temp) / "ledger.sqlite3")
                app = AppTest.from_file("chat.py").run()
                app.checkbox(key="model_assisted").check().run()
                app.chat_input(key="chat_input").set_value("I owe Aditya 3000").run()
                self.assertEqual(app.session_state.pending_clarification["kind"], "repeat")
                self.assertEqual(db.get_all_expenses_rows(), [])
                app.button(key="cancel_clarification").click().run()
                self.assertTrue(app.session_state.parser_model_assisted)

                app.chat_input(key="chat_input").set_value(
                    "I paid 3000 for the movie and Aditya owes me 1500"
                ).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.voice_draft["reminders"][0]["transaction_index"], 0)
                app.text_input[0].set_value("1000")
                next(button for button in app.button if button.label == "Apply correction").click().run()
                self.assertEqual(app.session_state.voice_draft["transactions"][0]["amount"], 3000)
                app.text_input[0].set_value("2800")
                next(button for button in app.button if button.label == "Apply correction").click().run()
                app.button(key="save_voice_draft").click().run()
                self.assertFalse(app.exception)
                row, = db.get_all_expenses_rows()
                reminder, = db.get_repayments()
                self.assertEqual((row["amount"], reminder["amount"], reminder["expense_id"]), (2800, 1500, row["id"]))
                app.button(key="undo_last_action").click().run()
                self.assertEqual(db.get_all_expenses_rows(), [])
                self.assertEqual(db.get_repayments(), [])
        finally:
            db.DB_PATH = original_path
