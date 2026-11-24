"""AI-powered polite debt reminder drafts using Anthropic Claude.

Drafts considerate, friendly, non-nagging messages between roommates.
Ensures no awkwardness or friction, keeping group harmony intact.
"""

import logging
import os
import random
from typing import Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

DRAFT_SYSTEM_PROMPT = """You are Roommate Peace Keeper's diplomatic reminder drafter.
Your goal is to write a warm, friendly, polite, and completely non-nagging message from a roommate who is owed money (the creditor) to a roommate who owes money (the debtor).

Tone guidelines:
- Casual, warm, considerate, empathetic.
- Absolutely NO nagging, passive-aggressive remarks, or cold corporate language.
- Mention the amount in Rupees (₹) and the purpose if provided.
- Keep it under 25 words.
- Encourage settling when convenient (e.g. 'whenever you have a sec', 'no rush', 'UPI works').
- Add a gentle, tasteful emoji (like 😊, 👍, ✨).
- Return ONLY the draft message itself, without quotation marks, intro, or sign-offs.
"""

FALLBACK_TEMPLATES = [
    "Hey {debtor}! When you get a free moment, could you send ₹{amount:.2f} for {item}? No rush at all, UPI works! 😊",
    "Hi {debtor}, hope your day is going well! Just a gentle nudge for ₹{amount:.2f} ({item}) whenever convenient. Thanks! ✨",
    "Hey {debtor}! Whenever you're free, please send across ₹{amount:.2f} for {item}. Any time today is great, thank you! 👍",
    "Hi {debtor}, just dropping a quick note for ₹{amount:.2f} for {item}. Whenever you get around to it, no stress! 🙌",
]


def draft_reminder_with_claude(
    debtor: str,
    creditor: str,
    amount: float,
    description: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """Generate a polite, human-like reminder message using Claude."""
    api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022").strip()

    item_desc = description.strip() if description else "recent shared expenses"

    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set. Using polite template draft.")
        return draft_reminder_fallback(debtor, creditor, amount, item_desc)

    user_prompt = f"""Creditor: {creditor}
Debtor: {debtor}
Amount: ₹{amount:.2f}
Description: {item_desc}

Draft a friendly, polite reminder now:"""

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=150,
            system=DRAFT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        draft = response.content[0].text.strip().strip('"').strip("'")
        return draft
    except Exception as e:
        logger.warning(f"Claude reminder draft failed: {e}. Falling back to template.")
        return draft_reminder_fallback(debtor, creditor, amount, item_desc)


def draft_reminder_fallback(
    debtor: str, creditor: str, amount: float, description: Optional[str] = None
) -> str:
    """Deterministic polite template generator."""
    item = description or "shared expenses"
    template = random.choice(FALLBACK_TEMPLATES)
    return template.format(
        debtor=debtor.strip().title(),
        creditor=creditor.strip().title(),
        amount=amount,
        item=item,
    )
