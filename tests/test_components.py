"""Unit tests for storage, parser fallbacks, and reminder drafts."""

import os
import tempfile
import pytest

from app.models import Expense, ReminderLog
from app.storage import SQLiteStorage
from app.parser import parse_expense_fallback, ExpenseParseError
from app.drafts import draft_reminder_fallback


@pytest.fixture
def temp_storage():
    """Create a temporary SQLite storage backend for isolated testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = SQLiteStorage(db_path=db_path)
    yield storage

    # Teardown
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_storage_members(temp_storage):
    """Test member registration and listing."""
    assert temp_storage.get_members("group_1") == []
    assert temp_storage.add_member("group_1", "Ravi", user_id=12345) is True
    assert temp_storage.add_member("group_1", "Anu") is True
    assert temp_storage.add_member("group_1", "  ravi  ") is True  # Duplicate / normalized

    members = temp_storage.get_members("group_1")
    assert sorted(members) == ["Anu", "Ravi"]


def test_storage_expenses(temp_storage):
    """Test expense insertion, retrieval, and clear."""
    exp = Expense(
        group_id="group_1",
        payer="Ravi",
        amount=600.0,
        description="Dinner",
        participants=["Ravi", "Anu", "Priya"],
    )
    exp_id = temp_storage.add_expense(exp)
    assert exp_id > 0

    expenses = temp_storage.get_expenses("group_1")
    assert len(expenses) == 1
    assert expenses[0].payer == "Ravi"
    assert expenses[0].amount == 600.0
    assert expenses[0].description == "Dinner"
    assert expenses[0].participants == ["Ravi", "Anu", "Priya"]


def test_storage_reminder_daily_cap(temp_storage):
    """Test daily cap limiting to prevent spamming roommates."""
    assert temp_storage.can_send_reminder("group_1", "Anu", daily_cap=2) is True

    # Log 1st reminder
    log1 = ReminderLog(
        group_id="group_1",
        debtor="Anu",
        creditor="Ravi",
        amount=200.0,
        message="Hey Anu, whenever free...",
        status="approved",
    )
    temp_storage.log_reminder(log1)
    assert temp_storage.get_daily_reminder_count("group_1", "Anu") == 1
    assert temp_storage.can_send_reminder("group_1", "Anu", daily_cap=2) is True

    # Log 2nd reminder
    log2 = ReminderLog(
        group_id="group_1",
        debtor="Anu",
        creditor="Ravi",
        amount=200.0,
        message="Gentle follow up...",
        status="approved",
    )
    temp_storage.log_reminder(log2)
    assert temp_storage.get_daily_reminder_count("group_1", "Anu") == 2
    # Cap reached!
    assert temp_storage.can_send_reminder("group_1", "Anu", daily_cap=2) is False

    # Discarded reminders do not count against daily cap
    log_discarded = ReminderLog(
        group_id="group_1",
        debtor="Anu",
        creditor="Ravi",
        amount=200.0,
        message="Draft message",
        status="discarded",
    )
    temp_storage.log_reminder(log_discarded)
    assert temp_storage.get_daily_reminder_count("group_1", "Anu") == 2


def test_parser_fallback_patterns():
    """Verify parsing of plain-language expense inputs."""
    # Pattern 1: 'Paid 600 for dinner, split 3'
    p1 = parse_expense_fallback(
        text="Paid 600 for dinner, split 3",
        sender_name="Shravya",
        known_members=["Shravya", "Shreya", "Rohan"],
    )
    assert p1.payer == "Shravya"
    assert p1.amount == 600.0
    assert "dinner" in p1.description.lower()
    assert len(p1.participants) == 3

    # Pattern 2: 'Ravi paid 300 for wifi, split between me, Ravi and Anu'
    p2 = parse_expense_fallback(
        text="Ravi paid 300 for wifi, split between me, Ravi and Anu",
        sender_name="Shravya",
        known_members=["Shravya", "Ravi", "Anu"],
    )
    assert p2.payer == "Ravi"
    assert p2.amount == 300.0
    assert "wifi" in p2.description.lower()
    assert "Shravya" in p2.participants
    assert "Ravi" in p2.participants
    assert "Anu" in p2.participants

    # Pattern 3: Invalid text without amount
    with pytest.raises(ExpenseParseError):
        parse_expense_fallback(
            text="Hello everyone who is cooking tonight?",
            sender_name="Shravya",
        )


def test_draft_reminder_fallback():
    """Verify friendly fallback reminder drafting."""
    draft = draft_reminder_fallback(
        debtor="Anu",
        creditor="Ravi",
        amount=250.0,
        description="groceries",
    )
    assert "Anu" in draft
    assert "250.00" in draft
    assert "groceries" in draft
