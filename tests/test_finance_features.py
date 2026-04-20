import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import ai_extractor
import dashboard_utils
import db


class FinanceFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="expense-tracker-tests-")
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir, "expenses.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

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


if __name__ == "__main__":
    unittest.main()
