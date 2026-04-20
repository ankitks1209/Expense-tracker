"""
db.py — SQLite database layer
-----------------------------
Supports both DEBIT (expense) and CREDIT (income) transactions.
"""

import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create/migrate the expenses table."""
    conn = get_conn()
    # Create table with transaction_type column
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            amount           REAL    NOT NULL,
            category         TEXT    NOT NULL DEFAULT 'Other',
            transaction_type TEXT    NOT NULL DEFAULT 'debit',
            date             TEXT    NOT NULL,
            note             TEXT,
            raw_input        TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Migrate existing DB if transaction_type column is missing
    cols = [row[1] for row in conn.execute("PRAGMA table_info(expenses)")]
    if "transaction_type" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN transaction_type TEXT NOT NULL DEFAULT 'debit'")
    conn.commit()
    conn.close()


def save_expense(data: dict) -> int:
    """
    Save a transaction. data keys:
        amount           (float)
        category         (str)
        transaction_type (str) — 'debit' or 'credit'
        date             (str, YYYY-MM-DD)
        note             (str, optional)
        raw_input        (str, optional)
    """
    conn = get_conn()
    cursor = conn.execute(
        """
        INSERT INTO expenses (amount, category, transaction_type, date, note, raw_input)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            float(data.get("amount", 0)),
            data.get("category", "Other"),
            data.get("transaction_type", "debit"),
            data.get("date", str(date.today())),
            data.get("note", ""),
            data.get("raw_input", ""),
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_expense_by_id(expense_id: int):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT id, amount, category, transaction_type, date, note, raw_input, created_at
        FROM expenses
        WHERE id = ?
        """,
        (expense_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_expense_row(row: dict) -> int:
    """Insert a row, preserving id/created_at when provided (for undo)."""
    conn = get_conn()
    cursor = conn.execute(
        """
        INSERT INTO expenses (id, amount, category, transaction_type, date, note, raw_input, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("id"),
            float(row.get("amount", 0)),
            row.get("category", "Other"),
            row.get("transaction_type", "debit"),
            row.get("date", str(date.today())),
            row.get("note", ""),
            row.get("raw_input", ""),
            row.get("created_at"),
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def insert_expense_rows(rows: list):
    if not rows:
        return
    conn = get_conn()
    conn.executemany(
        """
        INSERT INTO expenses (id, amount, category, transaction_type, date, note, raw_input, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.get("id"),
                float(row.get("amount", 0)),
                row.get("category", "Other"),
                row.get("transaction_type", "debit"),
                row.get("date", str(date.today())),
                row.get("note", ""),
                row.get("raw_input", ""),
                row.get("created_at"),
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def delete_expenses_by_ids(expense_ids: list):
    if not expense_ids:
        return
    conn = get_conn()
    conn.executemany("DELETE FROM expenses WHERE id = ?", [(int(i),) for i in expense_ids])
    conn.commit()
    conn.close()


def get_recent_expenses(limit: int = 12):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT id, amount, category, transaction_type, date, note, created_at
        FROM expenses
        ORDER BY date DESC, created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_all_expenses():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT id, amount, category, transaction_type, date, note, raw_input, created_at
        FROM expenses
        ORDER BY date DESC, created_at DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_all_expenses_rows():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, amount, category, transaction_type, date, note, raw_input, created_at
        FROM expenses
        ORDER BY id ASC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_totals():
    """Return (month, total_debit, total_credit) for past 12 months."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT
            strftime('%Y-%m', date) as month,
            SUM(CASE WHEN transaction_type='debit'  THEN amount ELSE 0 END) as debit,
            SUM(CASE WHEN transaction_type='credit' THEN amount ELSE 0 END) as credit
        FROM expenses
        WHERE date >= date('now', '-12 months')
        GROUP BY month
        ORDER BY month ASC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_category_totals(txn_type="debit"):
    """Return (category, total) for a given transaction type."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT category, SUM(amount) as total
        FROM expenses
        WHERE transaction_type = ?
        GROUP BY category
        ORDER BY total DESC
        """,
        (txn_type,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_daily_totals():
    """Return (date, debit, credit) for trend chart."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT
            date,
            SUM(CASE WHEN transaction_type='debit'  THEN amount ELSE 0 END) as debit,
            SUM(CASE WHEN transaction_type='credit' THEN amount ELSE 0 END) as credit
        FROM expenses
        GROUP BY date
        ORDER BY date ASC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_summary_stats():
    """Return overall financial summary."""
    conn = sqlite3.connect(DB_PATH)

    total_debit  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE transaction_type='debit'").fetchone()[0]
    total_credit = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE transaction_type='credit'").fetchone()[0]
    count        = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]

    top_expense_cat = conn.execute(
        """
        SELECT category FROM expenses WHERE transaction_type='debit'
        GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1
        """
    ).fetchone()

    top_income_cat = conn.execute(
        """
        SELECT category FROM expenses WHERE transaction_type='credit'
        GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1
        """
    ).fetchone()

    month_debit = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE transaction_type='debit' AND strftime('%Y-%m',date)=strftime('%Y-%m','now')"
    ).fetchone()[0]

    month_credit = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE transaction_type='credit' AND strftime('%Y-%m',date)=strftime('%Y-%m','now')"
    ).fetchone()[0]

    conn.close()
    return {
        "total_debit":       total_debit,
        "total_credit":      total_credit,
        "net_balance":       total_credit - total_debit,
        "total_count":       count,
        "top_expense_cat":   top_expense_cat[0]  if top_expense_cat  else "—",
        "top_income_cat":    top_income_cat[0]   if top_income_cat   else "—",
        "month_debit":       month_debit,
        "month_credit":      month_credit,
        "month_net":         month_credit - month_debit,
    }


def delete_expense(expense_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    conn.close()


def delete_all_expenses():
    conn = get_conn()
    conn.execute("DELETE FROM expenses")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'expenses'")
    conn.commit()
    conn.close()