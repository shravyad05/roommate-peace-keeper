"""Natural language expense parser powered by Anthropic Claude API with Pydantic validation.

Parses everyday roommate messages such as:
- 'Paid 600 for dinner, split 3'
- 'Ravi paid 300 for wifi, split between me, Ravi and Anu'
- 'Groceries 1200 paid by Priya for everyone'
"""

import json
import logging
import os
import re
from typing import List, Optional

from anthropic import Anthropic
from pydantic import ValidationError

from app.models import ParsedExpense

logger = logging.getLogger(__name__)


class ExpenseParseError(Exception):
    """Raised when an expense cannot be parsed or validated into structured format."""
    pass


PARSER_SYSTEM_PROMPT = """You are the precise expense parser for the Roommate Peace Keeper bot.
Your job is to convert natural language roommate messages into a single, valid JSON object.

Output JSON Schema:
{
  "payer": "<Name of the person who actually paid>",
  "amount": <positive float/integer amount paid in rupees>,
  "description": "<short item/category summary, e.g. dinner, wifi, groceries>",
  "participants": ["<Name 1>", "<Name 2>", ...]
}

Resolution Rules:
1. Payer identification:
   - If the message says 'I paid', 'Paid 600...', or omits a subject, the payer is the SENDER.
   - If a specific roommate is named (e.g. 'Ravi paid...'), the payer is that named person.
2. Participant identification:
   - 'me', 'myself', 'I' refers to the SENDER.
   - If the message specifies 'split 3', 'split between 3', or 'split with 2 others', and known roommates are provided, select appropriate roommates including the payer/sender.
   - If participants say 'everyone', 'all', or 'split all', include all known roommates (and the sender/payer).
   - Ensure the payer is included in participants if they shared in the item (almost always true unless stated as a gift/direct payment for someone else).
3. Amounts:
   - Extract the total monetary number. Ignore currency symbols like ₹, Rs, INR.
4. Output formatting:
   - Output ONLY a raw, valid JSON object. No explanations, no markdown codeblocks, no chat filler.
"""


def parse_expense_with_claude(
    text: str,
    sender_name: str,
    known_members: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> ParsedExpense:
    """Parse natural language expense message using Anthropic Claude API.
    
    Validates output using Pydantic. Raises ExpenseParseError on malformed or invalid data.
    """
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022").strip()

    # If no API key is provided, attempt intelligent local fallback
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set. Attempting regex/heuristic parser.")
        return parse_expense_fallback(text, sender_name, known_members)

    members_context = ", ".join(known_members) if known_members else "No pre-registered list provided."
    user_prompt = f"""Sender: {sender_name}
Known roommates: {members_context}
Message: "{text}"

Extract the expense JSON now:"""

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=PARSER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_content = response.content[0].text.strip()
        logger.debug(f"Claude raw response: {raw_content}")

        # Remove potential markdown fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_content, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        data = json.loads(cleaned)
        return ParsedExpense.model_validate(data)

    except (ValidationError, json.JSONDecodeError) as e:
        logger.warning(f"Claude JSON parse or validation failed: {e}. Trying fallback parser.")
        try:
            return parse_expense_fallback(text, sender_name, known_members)
        except Exception:
            raise ExpenseParseError(
                "I couldn't quite understand that expense structure.\n"
                "💡 Please rephrase, for example:\n"
                "• *'Paid 600 for dinner, split between Ravi, Anu, and me'*\n"
                "• *'Ravi paid 300 for wifi, split 3'*"
            )
    except Exception as e:
        logger.warning(f"Claude API request failed: {e}. Trying fallback parser.")
        try:
            return parse_expense_fallback(text, sender_name, known_members)
        except Exception:
            raise ExpenseParseError(
                "Unable to process expense right now. Please rephrase with payer, amount, item, and roommates."
            )


def parse_expense_fallback(
    text: str, sender_name: str, known_members: Optional[List[str]] = None
) -> ParsedExpense:
    """Deterministic fallback parser for offline use, unit tests, and network dropouts.
    
    Handles standard patterns like:
    - 'Paid 600 for dinner, split 3'
    - 'Ravi paid 300 for wifi, split between me, Ravi and Anu'
    - '1200 for groceries, split between Shravya and Shreya'
    """
    clean_sender = sender_name.strip().title() or "Me"
    members = [m.strip().title() for m in (known_members or [])]
    if clean_sender not in members:
        members.append(clean_sender)

    # 1. Extract amount (e.g. 600, 300.50, ₹1200, Rs. 450)
    amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if not amt_match:
        raise ExpenseParseError("Could not detect an amount. Example: 'Paid 500 for dinner'")
    amount = float(amt_match.group(1))

    # 2. Extract payer
    payer = clean_sender
    payer_match = re.search(r"^([A-Za-z]+)\s+paid", text, re.IGNORECASE)
    if payer_match:
        detected = payer_match.group(1).strip().title()
        if detected.lower() not in ["i", "we", "he", "she"]:
            payer = detected

    # 3. Extract description
    # Look for "for <description>"
    desc_match = re.search(r"(?:for|on)\s+([a-zA-Z0-9\s]+?)(?:,?\s*split|$)", text, re.IGNORECASE)
    if desc_match:
        description = desc_match.group(1).strip()
    else:
        # Fallback to word before or after amount
        description = "Shared expense"

    # 4. Extract participants
    participants = []
    split_match = re.search(r"split\s+(?:between|with|among)?\s*(.+)$", text, re.IGNORECASE)
    if split_match:
        split_part = split_match.group(1).strip()
        # Check if it is a number, like "split 3"
        num_split = re.search(r"^(\d+)", split_part)
        if num_split:
            count = int(num_split.group(1))
            # Take first `count` known members, ensuring payer is included
            selected = list(members)
            if payer not in selected:
                selected.insert(0, payer)
            participants = selected[:count] if len(selected) >= count else selected
        else:
            # Comma or 'and' separated names
            raw_names = re.split(r",|\band\b", split_part)
            for n in raw_names:
                n_clean = n.strip().title()
                if not n_clean:
                    continue
                if n_clean.lower() in ["me", "myself", "i"]:
                    participants.append(clean_sender)
                else:
                    participants.append(n_clean)
    elif "everyone" in text.lower() or "all" in text.lower():
        participants = list(members)
    else:
        # Default to all known members or at least payer
        participants = list(members) if len(members) >= 2 else [payer]

    # Ensure payer is in participants if not specified otherwise
    if payer not in participants:
        participants.append(payer)

    return ParsedExpense(
        payer=payer,
        amount=amount,
        description=description.capitalize() or "Shared expense",
        participants=participants,
    )
