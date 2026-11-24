"""Data models for Roommate Peace Keeper."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ParsedExpense(BaseModel):
    """Schema returned by Claude when parsing natural language expense messages."""

    payer: str = Field(..., description="Name of the person who paid the bill")
    amount: float = Field(..., gt=0, description="Total amount paid in currency units (must be > 0)")
    description: str = Field(..., min_length=1, description="Short summary of what was paid for")
    participants: List[str] = Field(
        ..., min_length=1, description="List of people sharing this expense, including payer if applicable"
    )

    @field_validator("payer")
    @classmethod
    def clean_payer(cls, v: str) -> str:
        cleaned = v.strip().title()
        if not cleaned:
            raise ValueError("Payer name cannot be empty")
        return cleaned

    @field_validator("participants")
    @classmethod
    def clean_participants(cls, v: List[str]) -> List[str]:
        cleaned = [p.strip().title() for p in v if p and p.strip()]
        if not cleaned:
            raise ValueError("Participants list cannot be empty")
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for p in cleaned:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    @field_validator("amount")
    @classmethod
    def round_amount(cls, v: float) -> float:
        return round(float(v), 2)


class Expense(BaseModel):
    """Full persisted expense record."""

    id: Optional[int] = None
    group_id: str
    payer: str
    amount: float
    description: str
    participants: List[str]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def share_per_person(self) -> float:
        if not self.participants:
            return 0.0
        return round(self.amount / len(self.participants), 2)


class SettlementTransfer(BaseModel):
    """Calculated minimal transfer between two roommates."""

    debtor: str = Field(..., description="The person who owes money (payer of debt)")
    creditor: str = Field(..., description="The person who is owed money (receiver)")
    amount: float = Field(..., gt=0, description="Amount to be transferred in rupees/currency")

    @field_validator("amount")
    @classmethod
    def round_transfer_amount(cls, v: float) -> float:
        return round(float(v), 2)


class ReminderLog(BaseModel):
    """Log entry of a drafted reminder and whether it was approved or discarded."""

    id: Optional[int] = None
    group_id: str
    debtor: str
    creditor: str
    amount: float
    message: str
    status: str = Field(..., description="'approved' or 'discarded'")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
