"""Storage layer for Roommate Peace Keeper.

Abstracts database operations behind BaseStorage interface so alternative backends
like Google Sheets, Airtable, or PostgreSQL can be plugged in seamlessly.
Provides a robust SQLite implementation out-of-the-box.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import List, Optional

from app.models import Expense, ReminderLog


class BaseStorage(ABC):
    """Abstract interface defining required storage operations."""

    @abstractmethod
    def add_member(self, group_id: str, name: str, user_id: Optional[int] = None) -> bool:
        """Register a roommate name in a group."""
        pass

    @abstractmethod
    def get_members(self, group_id: str) -> List[str]:
        """Get all registered roommate names for a group."""
        pass

    @abstractmethod
    def remove_member(self, group_id: str, name: str) -> bool:
        """Remove a member from a group."""
        pass

    @abstractmethod
    def add_expense(self, expense: Expense) -> int:
        """Save a confirmed expense and return its database ID."""
        pass

    @abstractmethod
    def get_expenses(self, group_id: str) -> List[Expense]:
        """Retrieve all expenses logged for a group."""
        pass

    @abstractmethod
    def clear_expenses(self, group_id: str) -> int:
        """Clear all expenses for a group (e.g. after complete settlement)."""
        pass

    @abstractmethod
    def log_reminder(self, log: ReminderLog) -> int:
        """Log a reminder decision ('approved' or 'discarded')."""
        pass

    @abstractmethod
    def get_daily_reminder_count(
        self, group_id: str, debtor: str, date_prefix: Optional[str] = None
    ) -> int:
        """Count approved reminders sent to a debtor today."""
        pass

    @abstractmethod
    def can_send_reminder(self, group_id: str, debtor: str, daily_cap: int = 2) -> bool:
        """Check whether daily reminder limit has been exceeded."""
        pass


class SQLiteStorage(BaseStorage):
    """Production SQLite storage backend."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DATABASE_PATH", "roommate_peace_keeper.db")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema with indexes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Members table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    telegram_user_id INTEGER,
                    joined_at TEXT NOT NULL,
                    UNIQUE(group_id, name)
                );
                """
            )

            # Expenses table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    payer TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    participants TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            # Reminders log table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    debtor TEXT NOT NULL,
                    creditor TEXT NOT NULL,
                    amount REAL NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_group ON expenses(group_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_group ON members(group_id);")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_group_debtor ON reminders(group_id, debtor, status, created_at);"
            )
            conn.commit()

    def add_member(self, group_id: str, name: str, user_id: Optional[int] = None) -> bool:
        cleaned = name.strip().title()
        if not cleaned:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO members (group_id, name, telegram_user_id, joined_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(group_id, name) DO UPDATE SET telegram_user_id = coalesce(excluded.telegram_user_id, members.telegram_user_id);
                    """,
                    (group_id, cleaned, user_id, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                return True
            except sqlite3.Error:
                return False

    def get_members(self, group_id: str) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM members WHERE group_id = ? ORDER BY name ASC;",
                (group_id,),
            )
            rows = cursor.fetchall()
            return [row["name"] for row in rows]

    def remove_member(self, group_id: str, name: str) -> bool:
        cleaned = name.strip().title()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM members WHERE group_id = ? AND name = ?;",
                (group_id, cleaned),
            )
            conn.commit()
            return cursor.rowcount > 0

    def add_expense(self, expense: Expense) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            participants_json = json.dumps(expense.participants)
            cursor.execute(
                """
                INSERT INTO expenses (group_id, payer, amount, description, participants, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    expense.group_id,
                    expense.payer,
                    expense.amount,
                    expense.description,
                    participants_json,
                    expense.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_expenses(self, group_id: str) -> List[Expense]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, group_id, payer, amount, description, participants, created_at
                FROM expenses
                WHERE group_id = ?
                ORDER BY id ASC;
                """,
                (group_id,),
            )
            rows = cursor.fetchall()

            expenses: List[Expense] = []
            for row in rows:
                try:
                    participants = json.loads(row["participants"])
                except Exception:
                    participants = [p.strip() for p in row["participants"].split(",") if p.strip()]

                expenses.append(
                    Expense(
                        id=row["id"],
                        group_id=row["group_id"],
                        payer=row["payer"],
                        amount=float(row["amount"]),
                        description=row["description"],
                        participants=participants,
                        created_at=row["created_at"],
                    )
                )
            return expenses

    def clear_expenses(self, group_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expenses WHERE group_id = ?;", (group_id,))
            conn.commit()
            return cursor.rowcount

    def log_reminder(self, log: ReminderLog) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO reminders (group_id, debtor, creditor, amount, message, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    log.group_id,
                    log.debtor,
                    log.creditor,
                    log.amount,
                    log.message,
                    log.status,
                    log.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_daily_reminder_count(
        self, group_id: str, debtor: str, date_prefix: Optional[str] = None
    ) -> int:
        if date_prefix is None:
            # UTC today prefix, e.g. "2026-11-24"
            date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) as cnt
                FROM reminders
                WHERE group_id = ? AND debtor = ? AND status = 'approved' AND created_at LIKE ?;
                """,
                (group_id, debtor.strip().title(), f"{date_prefix}%"),
            )
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0

    def can_send_reminder(self, group_id: str, debtor: str, daily_cap: int = 2) -> bool:
        count = self.get_daily_reminder_count(group_id, debtor)
        return count < daily_cap


# Global factory function
def get_storage(db_path: Optional[str] = None) -> BaseStorage:
    """Returns the configured storage backend."""
    return SQLiteStorage(db_path=db_path)
