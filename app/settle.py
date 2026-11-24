"""Pure settlement and debt simplification logic for Roommate Peace Keeper.

Uses integer paise arithmetic to guarantee exact balance reconciliation
without floating point drift, followed by greedy matching of the largest creditor
with the largest debtor for minimal transaction count.
"""

from typing import Dict, List, Optional
from app.models import Expense, SettlementTransfer


def calculate_net_balances(
    expenses: List[Expense], members: Optional[List[str]] = None
) -> Dict[str, float]:
    """Calculate net balances for all members in rupees (rounded to 2 decimal places).
    
    Positive balance: member is owed money (creditor).
    Negative balance: member owes money (debtor).
    Zero balance: member is settled.
    """
    paise_balances: Dict[str, int] = {}

    # Initialize all known members to 0 balance if provided
    if members:
        for m in members:
            cleaned = m.strip().title()
            if cleaned:
                paise_balances[cleaned] = 0

    for exp in expenses:
        payer = exp.payer.strip().title()
        participants = [p.strip().title() for p in exp.participants if p.strip()]

        if not participants:
            continue

        if payer not in paise_balances:
            paise_balances[payer] = 0

        # Total amount in integer paise
        total_paise = int(round(exp.amount * 100))
        n = len(participants)
        base_share = total_paise // n
        remainder = total_paise % n

        # Payer is credited the full amount
        paise_balances[payer] += total_paise

        # Distribute share among participants with exact paise remainder allocation
        for idx, participant in enumerate(participants):
            if participant not in paise_balances:
                paise_balances[participant] = 0

            # First `remainder` participants absorb 1 extra paise
            extra = 1 if idx < remainder else 0
            share_paise = base_share + extra
            paise_balances[participant] -= share_paise

    # Convert back to float rupees
    return {name: round(bal / 100.0, 2) for name, bal in sorted(paise_balances.items())}


def simplify_debts(net_balances: Dict[str, float]) -> List[SettlementTransfer]:
    """Given net balances in rupees, compute the minimum number of settlement transfers.
    
    Greedy matching between largest creditor and largest debtor.
    Guarantees termination in at most N-1 transactions.
    """
    # Work with integer paise to avoid precision/rounding errors
    creditors: List[List] = []  # [name, paise_owed_to_them]
    debtors: List[List] = []    # [name, paise_they_owe]

    for name, bal in net_balances.items():
        paise = int(round(bal * 100))
        if paise > 0:
            creditors.append([name, paise])
        elif paise < 0:
            debtors.append([name, -paise])

    transfers: List[SettlementTransfer] = []

    # Greedy matching: largest creditor meets largest debtor
    while creditors and debtors:
        # Sort descending by balance magnitude
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)

        creditor = creditors[0]
        debtor = debtors[0]

        transfer_paise = min(creditor[1], debtor[1])

        if transfer_paise > 0:
            transfers.append(
                SettlementTransfer(
                    debtor=debtor[0],
                    creditor=creditor[0],
                    amount=round(transfer_paise / 100.0, 2),
                )
            )

        creditor[1] -= transfer_paise
        debtor[1] -= transfer_paise

        if creditor[1] == 0:
            creditors.pop(0)
        if debtor[1] == 0:
            debtors.pop(0)

    return transfers


def calculate_settlements(
    expenses: List[Expense], members: Optional[List[str]] = None
) -> List[SettlementTransfer]:
    """Pure convenience function to calculate minimal settlements directly from expenses."""
    balances = calculate_net_balances(expenses, members)
    return simplify_debts(balances)
