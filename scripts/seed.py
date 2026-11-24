"""Seed script for Roommate Peace Keeper.

Populates the SQLite database with realistic sample roommates and expenses
to showcase immediate /balances and /settle calculations during demos.
"""

import os
import sys

# Ensure repository root is on Python module search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Expense
from app.settle import calculate_net_balances, calculate_settlements
from app.storage import SQLiteStorage


def seed_database(db_path: str = "roommate_peace_keeper.db", group_id: str = "demo_apartment_302"):
    print(f"🌱 Seeding database '{db_path}' for group '{group_id}'...")
    storage = SQLiteStorage(db_path=db_path)

    # Clear existing demo data
    storage.clear_expenses(group_id)

    # 1. Register roommates
    roommates = ["Shravya", "Shreya", "Rohan", "Ravi", "Anu"]
    for r in roommates:
        storage.add_member(group_id, r)
    print(f"✅ Registered {len(roommates)} roommates: {', '.join(roommates)}")

    # 2. Insert sample expenses
    sample_expenses = [
        Expense(
            group_id=group_id,
            payer="Shravya",
            amount=1500.0,
            description="Monthly Groceries (Zepto/Blinkit)",
            participants=["Shravya", "Shreya", "Rohan", "Ravi", "Anu"],
        ),
        Expense(
            group_id=group_id,
            payer="Shreya",
            amount=600.0,
            description="Friday Night Pizza",
            participants=["Shreya", "Rohan", "Ravi"],
        ),
        Expense(
            group_id=group_id,
            payer="Ravi",
            amount=300.0,
            description="High-Speed Fiber WiFi",
            participants=["Shravya", "Ravi", "Anu"],
        ),
        Expense(
            group_id=group_id,
            payer="Rohan",
            amount=250.0,
            description="Drinking Water Cans & Milk",
            participants=["Shravya", "Shreya", "Rohan", "Ravi", "Anu"],
        ),
    ]

    for exp in sample_expenses:
        exp_id = storage.add_expense(exp)
        print(f"  • Added Expense #{exp_id}: {exp.payer} paid ₹{exp.amount:.2f} for '{exp.description}'")

    # 3. Compute and display resulting net balances
    all_expenses = storage.get_expenses(group_id)
    balances = calculate_net_balances(all_expenses, roommates)

    print("\n📊 Current Net Balances:")
    for name, bal in balances.items():
        sign = "+" if bal > 0 else ""
        status = "creditor (is owed)" if bal > 0 else ("debtor (owes)" if bal < 0 else "settled")
        print(f"  {name:10}: {sign}₹{bal:.2f} ({status})")

    # 4. Compute minimal settlements
    transfers = calculate_settlements(all_expenses, roommates)
    print("\n🤝 Minimal Transfers Required to Settle:")
    for t in transfers:
        print(f"  💸 {t.debtor} pays {t.creditor} -> ₹{t.amount:.2f}")

    print("\n✨ Database seeded successfully! You can now start the bot or inspect balances.")


if __name__ == "__main__":
    db_file = os.getenv("DATABASE_PATH", "roommate_peace_keeper.db")
    seed_database(db_file)
