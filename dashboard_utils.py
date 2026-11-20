"""
dashboard_utils.py — Pure helpers for dashboard transforms and summaries.
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd


def prepare_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a normalized export frame with formatted dates."""
    export_frame = df[["date", "transaction_type", "category", "amount", "note"]].copy()
    recorded_dates = df["recorded_date"] if "recorded_date" in df else export_frame["date"]
    export_frame["date"] = pd.to_datetime(export_frame["date"], errors="coerce").dt.strftime("%d %b %Y").fillna(recorded_dates)
    return export_frame


def calculate_period_comparison(df: pd.DataFrame, today: Optional[date] = None) -> dict:
    """Calculate this month vs last month metrics."""
    current_day = today or date.today()
    this_month_start = current_day.replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    current = df[(df["date"] >= pd.Timestamp(this_month_start)) & (df["date"] <= pd.Timestamp(current_day))]
    previous = df[(df["date"] >= pd.Timestamp(last_month_start)) & (df["date"] <= pd.Timestamp(last_month_end))]

    def _totals(frame: pd.DataFrame) -> tuple[float, float]:
        income = frame[frame["transaction_type"] == "credit"]["amount"].sum()
        expense = frame[frame["transaction_type"] == "debit"]["amount"].sum()
        return float(income), float(expense)

    this_income, this_expense = _totals(current)
    last_income, last_expense = _totals(previous)

    income_change = ((this_income - last_income) / last_income) * 100 if last_income else 0
    expense_change = ((this_expense - last_expense) / last_expense) * 100 if last_expense else 0

    return {
        "this_month": {
            "income": this_income,
            "expense": this_expense,
        },
        "last_month": {
            "income": last_income,
            "expense": last_expense,
        },
        "income_change_pct": round(income_change, 2),
        "expense_change_pct": round(expense_change, 2),
        "income_arrow": "📈" if income_change >= 0 else "📉",
        "expense_arrow": "📈" if expense_change >= 0 else "📉",
        "month_label": current_day.strftime("%B %Y"),
    }


def budget_progress(spent: float, budget: float) -> dict:
    """Return progress bar state for a category budget."""
    budget_value = float(budget or 0)
    spent_value = float(spent or 0)
    pct = (spent_value / max(budget_value, 1)) * 100

    if spent_value == budget_value and budget_value > 0:
        return {"percent": 100.0, "status": "✓ Limit reached", "bar_color": "#d97706"}
    if pct > 100:
        return {
            "percent": round(pct, 2),
            "status": "❌ Over budget",
            "bar_color": "#dc2626",
        }
    if pct >= 80:
        return {
            "percent": round(pct, 2),
            "status": "⚠️ Near limit",
            "bar_color": "#d97706",
        }
    return {
        "percent": round(pct, 2),
        "status": "✓ On track",
        "bar_color": "#16a34a",
    }
