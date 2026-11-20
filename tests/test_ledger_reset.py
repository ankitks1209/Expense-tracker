import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import db


class LedgerResetTests(unittest.TestCase):
    def test_demo_sessions_are_isolated(self):
        with patch.dict(os.environ, {"ENMA_DEMO_MODE": "1"}):
            def demo():
                import db
                import streamlit as st
                db.init_db()
                if st.button("Record"):
                    db.save_expense({"amount": 100})
                st.metric("Entries", len(db.get_all_expenses_rows()))
            first = AppTest.from_function(demo).run()
            first.button[0].click().run()
            self.assertEqual(first.metric[0].value, "1")
            second = AppTest.from_function(demo).run()
            self.assertEqual(second.metric[0].value, "0")
            self.assertEqual(first.run().metric[0].value, "1")

    def test_reset_is_visible_in_both_pages_and_cancel_clear_undo_work(self):
        original_path = db.DB_PATH
        try:
            with TemporaryDirectory() as temp, patch("streamlit.secrets", {}), patch.dict(
                os.environ, {"ENMA_LEDGER_PASSCODE": ""}
            ):
                db.DB_PATH = str(Path(temp) / "ledger.sqlite3")
                db.init_db()
                db.save_expense({"amount": 3000, "note": "Movie", "repayment": {"person": "Aditya", "amount": 1500}})
                db.add_repayment("pay", "Rahul", 350, "Standalone debt")
                rows = db.get_all_expenses_rows()
                reminders = db.get_repayments()
                chat = AppTest.from_file("chat.py").run()
                self.assertEqual(chat.button(key="reset_all_transactions").label, "Reset all")
                chat.button(key="reset_all_transactions").click().run()
                self.assertEqual(db.get_all_expenses_rows(), rows)
                chat.button(key="cancel_reset_all_transactions").click().run()
                self.assertEqual(db.get_repayments(), reminders)
                chat.button(key="reset_all_transactions").click().run()
                chat.button(key="confirm_reset_all_transactions").click().run()
                self.assertFalse(chat.exception)
                self.assertEqual(db.get_all_expenses_rows(), [])
                self.assertEqual(db.get_repayments(), [])
                chat.button(key="undo_ledger_reset").click().run()
                self.assertFalse(chat.exception)
                self.assertEqual(db.get_all_expenses_rows(), rows)
                self.assertEqual(db.get_repayments(), reminders)
                dashboard = AppTest.from_file("dashboard.py").run()
                self.assertEqual(dashboard.button(key="reset_all_transactions").label, "Reset all")
        finally:
            db.DB_PATH = original_path
