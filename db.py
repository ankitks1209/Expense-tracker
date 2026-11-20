"""
db.py — SQLite database layer
-----------------------------
Supports both DEBIT (expense) and CREDIT (income) transactions.
"""

import sqlite3
import os
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")


def _database_path():
    if os.environ.get("ENMA_DEMO_MODE") == "1":
        from tempfile import TemporaryDirectory
        import streamlit as st
        if "_demo_directory" not in st.session_state:
            st.session_state._demo_directory = TemporaryDirectory(prefix="enma-demo-")
        return os.path.join(st.session_state._demo_directory.name, "demo.db")
    return DB_PATH


def get_conn():
    conn = sqlite3.connect(_database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repayments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL CHECK(direction IN ('collect', 'pay')),
            person TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            note TEXT NOT NULL,
            due_date TEXT,
            expense_id INTEGER REFERENCES expenses(id) ON DELETE CASCADE,
            settlement_id INTEGER UNIQUE REFERENCES expenses(id) ON DELETE SET NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_preferences (
            phrase TEXT PRIMARY KEY,
            category TEXT NOT NULL
        )
    """)
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        month TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL,
        PRIMARY KEY(month, category))""")
    conn.commit()
    conn.close()


class DuplicateExpense(ValueError):
    pass


def _expense_values(data):
    try:
        amount = Decimal(str(data["amount"]))
    except (InvalidOperation, KeyError):
        raise ValueError("Enter a numeric amount.") from None
    if not amount.is_finite() or not 0 < amount < Decimal("1000000000000"):
        raise ValueError("Enter a positive amount below ₹1 trillion.")
    if amount % Decimal("0.01"):
        raise ValueError("Enter an amount with at most two decimal places.")
    txn_type = data.get("transaction_type", "debit")
    if txn_type not in ("debit", "credit"):
        raise ValueError("Select debit or credit.")
    txn_date = date.fromisoformat(data.get("date", date.today().isoformat())).isoformat()
    return (
        float(amount), data.get("category", "Other"), txn_type, txn_date,
        data.get("note", ""), data.get("raw_input", ""),
    )


def save_expenses(transactions, *, check_duplicates=False):
    """Validate and save an entire batch in one transaction."""
    ids, _ = save_chat_entries(transactions, (), check_duplicates=check_duplicates)
    return ids


def save_chat_entries(transactions, reminders, *, check_duplicates=False):
    """Save ledger entries and standalone reminders as one batch."""
    transactions = list(transactions)
    reminders = list(reminders)
    values = [_expense_values(txn) for txn in transactions]
    if not values and not reminders:
        raise ValueError("No entries to save.")
    split_totals = []
    for transaction in transactions:
        repayment = transaction.get("repayment")
        amount = _expense_values({"amount": repayment["amount"]})[0] if repayment else 0
        split_totals.append(Decimal(str(amount)))
    for reminder in reminders:
        index = reminder.get("transaction_index")
        if index is None:
            continue
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(transactions):
            raise ValueError("The repayment must refer to an expense in this draft.")
        if reminder["direction"] != "collect" or values[index][2] != "debit":
            raise ValueError("Only money to collect can be linked to an expense.")
        split_totals[index] += Decimal(str(_expense_values({"amount": reminder["amount"]})[0]))
    for total, row in zip(split_totals, values):
        if total > Decimal(str(row[0])):
            raise ValueError("The total repayment cannot exceed the expense.")
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = []
        for transaction, row in zip(transactions, values):
            amount, category, txn_type, txn_date, note, _ = row
            if check_duplicates and conn.execute(
                """
                SELECT 1 FROM expenses
                WHERE amount = ? AND category = ? AND transaction_type = ? AND date = ?
                AND LOWER(TRIM(note)) = LOWER(TRIM(?))
                AND created_at >= datetime('now', 'localtime', '-10 minutes')
                LIMIT 1
                """,
                (amount, category, txn_type, txn_date, note),
            ).fetchone():
                raise DuplicateExpense("A matching entry already exists. Save anyway or cancel?")
            cursor = conn.execute(
                """
                INSERT INTO expenses (amount, category, transaction_type, date, note, raw_input)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            ids.append(cursor.lastrowid)
            repayment = transaction.get("repayment")
            if repayment:
                if txn_type != "debit" or Decimal(str(repayment["amount"])) > Decimal(str(amount)):
                    raise ValueError("The repayment cannot exceed the expense.")
                _insert_repayment(conn, "collect", repayment.get("person", ""), repayment["amount"],
                                  note, repayment.get("due_date"), expense_id=cursor.lastrowid)
        reminder_ids = []
        for reminder in reminders:
            index = reminder.get("transaction_index")
            if index is None and check_duplicates and conn.execute(
                """SELECT 1 FROM repayments WHERE expense_id IS NULL AND settlement_id IS NULL
                   AND direction = ? AND lower(trim(person)) = lower(trim(?)) AND amount = ?
                   AND due_date IS ? AND lower(trim(note)) = lower(trim(?)) LIMIT 1""",
                (reminder["direction"], reminder["person"], reminder["amount"],
                 reminder.get("due_date"), reminder["note"]),
            ).fetchone():
                raise DuplicateExpense("A matching unpaid reminder already exists.")
            reminder_ids.append(_insert_repayment(
                conn, reminder["direction"], reminder["person"], reminder["amount"], reminder["note"],
                reminder.get("due_date"), expense_id=ids[index] if index is not None else None,
            ))
    return ids, reminder_ids


def _insert_repayment(conn, direction, person, amount, note, due_date, *, expense_id=None):
    amount = _expense_values({"amount": amount})[0]
    due_date = date.fromisoformat(due_date).isoformat() if due_date else None
    return conn.execute(
        """
        INSERT INTO repayments (direction, person, amount, note, due_date, expense_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (direction, person.strip(), amount, note.strip(), due_date, expense_id),
    ).lastrowid


def add_repayment(direction, person, amount, note, due_date=None):
    with closing(get_conn()) as conn, conn:
        return _insert_repayment(conn, direction, person, amount, note, due_date)


def category_preferences():
    with closing(get_conn()) as conn:
        return dict(conn.execute("SELECT phrase, category FROM category_preferences ORDER BY phrase"))


def set_category_preference(phrase, category):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "INSERT INTO category_preferences VALUES (?, ?) ON CONFLICT(phrase) DO UPDATE SET category = excluded.category",
            (phrase, category),
        )


def remove_category_preference(phrase):
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM category_preferences WHERE phrase = ?", (phrase,))


def update_repayment(repayment_id, person, due_date):
    due_date = date.fromisoformat(due_date).isoformat() if due_date else None
    with closing(get_conn()) as conn, conn:
        conn.execute(
            "UPDATE repayments SET person = ?, due_date = ? WHERE id = ? AND settlement_id IS NULL",
            (person.strip(), due_date, repayment_id),
        )


def get_repayments():
    with closing(get_conn()) as conn:
        return [dict(row) for row in conn.execute(
            """
            SELECT * FROM repayments WHERE settlement_id IS NULL
            ORDER BY due_date IS NULL, due_date, id DESC
            """
        )]


def settle_repayment(repayment_id):
    """Record payment once and close the reminder in the same transaction."""
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM repayments WHERE id = ? AND settlement_id IS NULL", (repayment_id,),
        ).fetchone()
        if row is None:
            return None
        collect = row["direction"] == "collect"
        note = "Repayment from" if collect else "Repayment to"
        note = f"{note} {row['person']}" if row["person"] else "Split repayment"
        if row["note"]:
            note = f"{note} · {row['note']}"
        original = conn.execute("SELECT category FROM expenses WHERE id = ?", (row["expense_id"],)).fetchone()
        values = _expense_values({
            "amount": row["amount"], "transaction_type": "credit" if collect else "debit",
            "category": "Reimbursement" if collect else original["category"] if original else "Other",
            "note": note,
        })
        settlement_id = conn.execute(
            "INSERT INTO expenses (amount, category, transaction_type, date, note, raw_input) VALUES (?, ?, ?, ?, ?, ?)",
            values,
        ).lastrowid
        conn.execute("UPDATE repayments SET settlement_id = ? WHERE id = ?", (settlement_id, repayment_id))
        return settlement_id


def remove_repayment(repayment_id):
    with closing(get_conn()) as conn, conn:
        conn.execute("DELETE FROM repayments WHERE id = ? AND settlement_id IS NULL", (repayment_id,))


def move_expense_to_repayments(expense_id, direction, person):
    """Replace an incorrectly logged expense with a pending reminder atomically."""
    if direction not in {"collect", "pay"} or not person.strip():
        raise ValueError("Choose who owes the money and enter their name.")
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if row is None or row["transaction_type"] != "debit":
            raise ValueError("Select a saved expense to move to Repayments.")
        if conn.execute(
            "SELECT 1 FROM repayments WHERE expense_id = ? OR settlement_id = ?", (expense_id, expense_id),
        ).fetchone():
            raise ValueError("This entry is already tied to a repayment. Review that repayment first.")
        reminder_id = _insert_repayment(conn, direction, person, row["amount"], "", None)
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return {"row": dict(row), "reminder_id": reminder_id}


def undo_move_to_repayments(payload):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        reminder = conn.execute(
            "SELECT settlement_id FROM repayments WHERE id = ?", (payload["reminder_id"],),
        ).fetchone()
        if reminder is None or reminder["settlement_id"] is not None:
            raise ValueError("This reminder has changed. Undo its payment first, or review it in Repayments.")
        row = payload["row"]
        conn.execute(
            """
            INSERT INTO expenses (id, amount, category, transaction_type, date, note, raw_input, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["id"], *_expense_values(row), row["created_at"]),
        )
        conn.execute("DELETE FROM repayments WHERE id = ?", (payload["reminder_id"],))


def save_expense(data: dict) -> int:
    return save_expenses([data])[0]


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
    return insert_expense_rows([row])[0]


def insert_expense_rows(rows: list):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = []
        for row in rows:
            cursor = conn.execute(
                """
                INSERT INTO expenses (id, amount, category, transaction_type, date, note, raw_input, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row.get("id"), *_expense_values(row), row.get("created_at")),
            )
            ids.append(cursor.lastrowid)
        for row in rows:
            for repayment in row.get("repayments", []):
                conn.execute(
                    """
                    INSERT INTO repayments (id, direction, person, amount, note, due_date, expense_id, settlement_id)
                    VALUES (:id, :direction, :person, :amount, :note, :due_date, :expense_id, :settlement_id)
                    ON CONFLICT(id) DO UPDATE SET settlement_id = excluded.settlement_id
                    WHERE repayments.settlement_id IS NULL
                    """,
                    repayment,
                )
        return ids


def delete_expenses_by_ids(expense_ids: list):
    undo_chat_entries(expense_ids, ())


def undo_chat_entries(expense_ids, reminder_ids):
    if not expense_ids and not reminder_ids:
        return
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for reminder_id in reminder_ids:
            if conn.execute(
                "SELECT 1 FROM repayments WHERE id = ? AND settlement_id IS NOT NULL", (reminder_id,),
            ).fetchone():
                raise ValueError("This reminder has been settled. Undo the repayment in the Dashboard first.")
            conn.execute("DELETE FROM repayments WHERE id = ?", (reminder_id,))
        for expense_id in expense_ids:
            if conn.execute(
                "SELECT 1 FROM repayments WHERE expense_id = ? AND settlement_id IS NOT NULL", (expense_id,),
            ).fetchone():
                raise ValueError("This split has been repaid. Undo the repayment in the Dashboard first.")
            conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


def get_recent_expenses(limit: int = 12):
    conn = sqlite3.connect(_database_path())
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
    conn = sqlite3.connect(_database_path())
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
    conn = sqlite3.connect(_database_path())
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
    conn = sqlite3.connect(_database_path())
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
    conn = sqlite3.connect(_database_path())
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
    conn = sqlite3.connect(_database_path())

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
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not row:
            return None
        repayments = conn.execute(
            "SELECT * FROM repayments WHERE expense_id = ? OR settlement_id = ?", (expense_id, expense_id),
        ).fetchall()
        if any(r["expense_id"] == expense_id and r["settlement_id"] is not None for r in repayments):
            raise ValueError("This entry has a recorded repayment. Undo the repayment before deleting the original expense.")
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return {**dict(row), "repayments": [dict(repayment) for repayment in repayments]}


def delete_all_expenses():
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")}
        for repayment in conn.execute("SELECT * FROM repayments"):
            owner = repayment["expense_id"] or repayment["settlement_id"]
            if owner in rows:
                rows[owner].setdefault("repayments", []).append(dict(repayment))
        conn.execute("DELETE FROM expenses")
        return list(rows.values())


def monthly_budgets(month):
    with closing(get_conn()) as conn:
        return dict(conn.execute("SELECT category, amount FROM budgets WHERE month = ?", (month,)))


def set_monthly_budget(month, category, amount):
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO budgets VALUES (?, ?, ?)",
                     (month, category, _expense_values({"amount": amount})[0]))


def reset_ledger():
    """Snapshot and clear transactions and all repayment reminders together."""
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        snapshot = {
            "budgets": [dict(row) for row in conn.execute("SELECT * FROM budgets")],
            "expenses": [dict(row) for row in conn.execute("SELECT * FROM expenses ORDER BY id")],
            "repayments": [dict(row) for row in conn.execute("SELECT * FROM repayments ORDER BY id")],
        }
        conn.execute("DELETE FROM budgets")
        conn.execute("DELETE FROM repayments")
        conn.execute("DELETE FROM expenses")
        return snapshot


def restore_ledger(snapshot):
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """
            INSERT INTO expenses (id, amount, category, transaction_type, date, note, raw_input, created_at)
            VALUES (:id, :amount, :category, :transaction_type, :date, :note, :raw_input, :created_at)
            """,
            snapshot["expenses"],
        )
        conn.executemany(
            """
            INSERT INTO repayments (id, direction, person, amount, note, due_date, expense_id, settlement_id)
            VALUES (:id, :direction, :person, :amount, :note, :due_date, :expense_id, :settlement_id)
            """,
            snapshot["repayments"],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO budgets VALUES (:month, :category, :amount)", snapshot.get("budgets", [])
        )
