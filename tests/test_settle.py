"""Pytest test suite for settlement engine in Roommate Peace Keeper.

Tests cover:
1. Simple 3-person split
2. Already settled / zero balances
3. Paise rounding (e.g. 100 split 3 ways without paise loss)
4. Chain where A owes B and B owes C (simplified to direct transfer A -> C)
5. Additional edge cases: single participant, unequal debts, empty expenses
"""

import pytest
from app.models import Expense, SettlementTransfer
from app.settle import (
    calculate_net_balances,
    simplify_debts,
    calculate_settlements,
)


def test_simple_three_person_split():
    """Case 1: Ravi pays 600 for dinner split equally between Ravi, Anu, and Priya.
    
    Each person's share = 200.
    Ravi is owed 400.
    Anu owes 200.
    Priya owes 200.
    Settlement: Anu -> Ravi 200, Priya -> Ravi 200.
    """
    expense = Expense(
        group_id="group_1",
        payer="Ravi",
        amount=600.0,
        description="Dinner",
        participants=["Ravi", "Anu", "Priya"],
    )

    balances = calculate_net_balances([expense])
    assert balances["Ravi"] == 400.0
    assert balances["Anu"] == -200.0
    assert balances["Priya"] == -200.0

    transfers = simplify_debts(balances)
    assert len(transfers) == 2

    # Check that total transfers match debts
    transfer_map = {(t.debtor, t.creditor): t.amount for t in transfers}
    assert transfer_map.get(("Anu", "Ravi")) == 200.0
    assert transfer_map.get(("Priya", "Ravi")) == 200.0


def test_already_settled():
    """Case 2: Everyone has balanced out, no transfers should be generated."""
    # Scenario A: No expenses at all
    empty_transfers = calculate_settlements([], members=["Ravi", "Anu"])
    assert empty_transfers == []

    # Scenario B: Ravi pays 300 for Ravi and Anu (Anu owes 150),
    # then Anu pays 300 for Ravi and Anu (Ravi owes 150) -> net 0
    exp1 = Expense(
        group_id="group_1",
        payer="Ravi",
        amount=300.0,
        description="Groceries",
        participants=["Ravi", "Anu"],
    )
    exp2 = Expense(
        group_id="group_1",
        payer="Anu",
        amount=300.0,
        description="Electricity bill",
        participants=["Ravi", "Anu"],
    )

    balances = calculate_net_balances([exp1, exp2])
    assert balances["Ravi"] == 0.0
    assert balances["Anu"] == 0.0

    transfers = simplify_debts(balances)
    assert transfers == []


def test_paise_rounding_three_way_split():
    """Case 3: 100 rupees split 3 ways (100 / 3 = 33.3333...).
    
    In integer paise arithmetic:
    10000 paise / 3 = 3333 paise each, remainder 1 paise.
    First participant pays 3334 paise (Rs 33.34), others pay 3333 paise (Rs 33.33).
    Sum of net balances must sum to exactly zero (zero paise leakage).
    """
    expense = Expense(
        group_id="group_1",
        payer="Shravya",
        amount=100.0,
        description="Snacks",
        participants=["Shravya", "Shreya", "Rohan"],
    )

    balances = calculate_net_balances([expense])
    # Shravya paid 100.0, her share is 33.34, net balance = +66.66
    # Shreya owes 33.33
    # Rohan owes 33.33
    total_balance = sum(balances.values())
    assert abs(total_balance) < 0.01  # Exact zero sum

    transfers = simplify_debts(balances)
    assert len(transfers) == 2

    total_settled = sum(t.amount for t in transfers)
    assert round(total_settled, 2) == 66.66

    creditors = {t.creditor for t in transfers}
    debtors = {t.debtor for t in transfers}
    assert creditors == {"Shravya"}
    assert debtors == {"Shreya", "Rohan"}


def test_debt_chain_simplification():
    """Case 4: Chain where A owes B and B owes C.
    
    Example:
    1. B (Bob) pays 100 for Bob and A (Alice). Alice owes Bob 50.
    2. C (Charlie) pays 100 for Charlie and B (Bob). Bob owes Charlie 50.
    
    Net:
    Alice: -50
    Bob: +50 - 50 = 0
    Charlie: +50
    
    Settlement: Alice pays Charlie 50 directly. Bob is eliminated from transactions.
    """
    exp1 = Expense(
        group_id="group_1",
        payer="Bob",
        amount=100.0,
        description="Breakfast",
        participants=["Bob", "Alice"],
    )
    exp2 = Expense(
        group_id="group_1",
        payer="Charlie",
        amount=100.0,
        description="Lunch",
        participants=["Charlie", "Bob"],
    )

    balances = calculate_net_balances([exp1, exp2])
    assert balances["Alice"] == -50.0
    assert balances["Bob"] == 0.0
    assert balances["Charlie"] == 50.0

    transfers = simplify_debts(balances)
    # Crucial assertion: exactly 1 transfer instead of 2 chained transfers
    assert len(transfers) == 1
    assert transfers[0].debtor == "Alice"
    assert transfers[0].creditor == "Charlie"
    assert transfers[0].amount == 50.0


def test_large_group_greedy_simplification():
    """Verify greedy matching minimizes transfers in a 4-person group with multiple debts."""
    # Person A pays 1000 for A, B, C, D (250 each)
    # Person B pays 500 for B, C (250 each)
    exp1 = Expense(
        group_id="grp",
        payer="A",
        amount=1000.0,
        description="Rent advance",
        participants=["A", "B", "C", "D"],
    )
    exp2 = Expense(
        group_id="grp",
        payer="B",
        amount=500.0,
        description="Wifi setup",
        participants=["B", "C"],
    )

    # Balances:
    # A: +1000 - 250 = +750
    # B: -250 + 500 - 250 = 0
    # C: -250 - 250 = -500
    # D: -250 = -250
    # Transfers:
    # C -> A: 500
    # D -> A: 250
    balances = calculate_net_balances([exp1, exp2])
    assert balances["A"] == 750.0
    assert balances["B"] == 0.0
    assert balances["C"] == -500.0
    assert balances["D"] == -250.0

    transfers = simplify_debts(balances)
    assert len(transfers) == 2
    transfer_dict = {(t.debtor, t.creditor): t.amount for t in transfers}
    assert transfer_dict[("C", "A")] == 500.0
    assert transfer_dict[("D", "A")] == 250.0


def test_payer_not_in_participants():
    """Test when someone pays for others entirely (e.g., Mom pays 500 for Ravi and Anu)."""
    exp = Expense(
        group_id="grp",
        payer="Mom",
        amount=500.0,
        description="Gift snacks",
        participants=["Ravi", "Anu"],
    )
    balances = calculate_net_balances([exp])
    assert balances["Mom"] == 500.0
    assert balances["Ravi"] == -250.0
    assert balances["Anu"] == -250.0

    transfers = simplify_debts(balances)
    assert len(transfers) == 2
    assert all(t.creditor == "Mom" for t in transfers)
