"""Roommate Peace Keeper - Telegram Bot.

Features:
- Plain-language expense logging parsed by Claude and validated with Pydantic
- Confirmation card with [Confirm] and [Cancel] inline buttons
- /members to view or add roommates
- /balances to inspect net debts and credits
- /settle to compute minimum transfers via greedy debt simplification
- Approval-gated polite reminder drafts powered by Claude with a daily cap
- Optional ElevenLabs Speech-to-Text voice note processing
"""

import io
import json
import logging
import os
import sys
import uuid
from typing import Dict, Any, List

# Ensure repository root is on sys.path so running directly works from any directory
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from app.drafts import draft_reminder_with_claude
from app.models import Expense, ParsedExpense, ReminderLog
from app.parser import parse_expense_with_claude, ExpenseParseError
from app.settle import calculate_net_balances, calculate_settlements
from app.storage import get_storage

# Load environment variables
load_dotenv()

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Ephemeral in-memory caches for interactive confirmation cards
PENDING_EXPENSES: Dict[str, Dict[str, Any]] = {}
PENDING_REMINDERS: Dict[str, Dict[str, Any]] = {}

# Storage instance
storage = get_storage()


def get_group_id(update: Update) -> str:
    """Extract unique group/chat ID."""
    if update.effective_chat:
        return str(update.effective_chat.id)
    return "default_group"


def get_sender_display_name(update: Update) -> str:
    """Extract display name of sender."""
    if update.effective_user:
        name = update.effective_user.first_name or update.effective_user.username or "Roommate"
        return name.strip().title()
    return "Roommate"


# ============================================================================
# Command Handlers
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message and quick-start instructions."""
    group_id = get_group_id(update)
    user_name = get_sender_display_name(update)
    storage.add_member(group_id, user_name, update.effective_user.id if update.effective_user else None)

    welcome_text = (
        "🏠 *Welcome to Roommate Peace Keeper!* ✌️\n\n"
        "No more passive-aggressive sticky notes or tedious spreadsheets.\n"
        "Just talk naturally in this group, and I'll keep your expenses balanced and relationships happy!\n\n"
        "💡 *How to use:*\n"
        "• *Log expenses in plain English:*\n"
        "  _\"Paid 600 for dinner, split 3\"_\n"
        "  _\"Ravi paid 300 for wifi, split between me, Ravi and Anu\"_\n"
        "• `/members` — View or add roommates\n"
        "• `/balances` — View net balances (who is up, who owes)\n"
        "• `/settle` — Calculate minimal transfers & review polite reminders\n"
        "• `/help` — View full command guide\n\n"
        "🛡️ *Golden Rule:* Nothing is saved without your [Confirm], and *no reminders are ever sent* without your explicit approval!"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help guide and cheat sheet."""
    help_text = (
        "📖 *Roommate Peace Keeper - Guide*\n\n"
        "*Logging an Expense:*\n"
        "Simply type what happened:\n"
        "• `Paid 1200 for groceries, split with Shreya and Rohan`\n"
        "• `Ravi paid 450 for cleaning supplies split 3`\n"
        "• `Paid 200 for milk` (auto-splits among group members)\n\n"
        "*Commands:*\n"
        "• `/members` — List all registered roommates\n"
        "• `/members add <Name1>, <Name2>` — Register roommates\n"
        "• `/balances` — See current net balances\n"
        "• `/settle` — Find minimum payments & draft gentle reminders\n"
        "• `/clear` — Reset settled expenses after payment\n\n"
        "🎙️ *Voice Notes:*\n"
        "Send a quick voice note describing your expense if voice support is enabled!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /members and /members add <Name1>, <Name2>."""
    group_id = get_group_id(update)
    args = context.args

    if args and args[0].lower() == "add":
        names_str = " ".join(args[1:])
        raw_names = [n.strip() for n in names_str.replace("and", ",").split(",") if n.strip()]
        if not raw_names:
            await update.message.reply_text(
                "⚠️ Please provide names to add, e.g.:\n`/members add Ravi, Anu, Priya`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        added = []
        for name in raw_names:
            if storage.add_member(group_id, name):
                added.append(name.title())

        current = storage.get_members(group_id)
        await update.message.reply_text(
            f"✅ Added {len(added)} roommate(s): *{', '.join(added)}*\n\n"
            f"👥 *All Registered Members:* {', '.join(current)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # List registered members
    members = storage.get_members(group_id)
    # Ensure current user is in members list
    sender = get_sender_display_name(update)
    if sender and sender not in members:
        storage.add_member(group_id, sender, update.effective_user.id if update.effective_user else None)
        members = storage.get_members(group_id)

    if not members:
        await update.message.reply_text(
            "👥 No roommates registered yet.\nAdd roommates with: `/members add Ravi, Anu, Priya`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = "👥 *Registered Roommates:*\n" + "\n".join(f"• {m}" for m in members)
    msg += "\n\n_To add more: `/members add Name1, Name2`_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def balances_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current net balances for all roommates."""
    group_id = get_group_id(update)
    expenses = storage.get_expenses(group_id)
    members = storage.get_members(group_id)

    if not expenses:
        await update.message.reply_text(
            "📊 No expenses logged yet in this group!\nLog one by typing: _'Paid 600 for dinner, split 3'_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    balances = calculate_net_balances(expenses, members)

    lines = ["📊 *Current Net Balances:*\n"]
    for member, bal in balances.items():
        if bal > 0.00:
            lines.append(f"🟢 *{member}*: +₹{bal:.2f} _(is owed money)_")
        elif bal < -0.00:
            lines.append(f"🔴 *{member}*: -₹{abs(bal):.2f} _(owes money)_")
        else:
            lines.append(f"⚪ *{member}*: ₹0.00 _(settled)_")

    lines.append("\n💡 Type `/settle` to see the minimal settlement plan.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def settle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Calculate minimal settlement transfers and present Claude reminder approval drafts."""
    group_id = get_group_id(update)
    expenses = storage.get_expenses(group_id)
    members = storage.get_members(group_id)

    if not expenses:
        await update.message.reply_text(
            "🎉 All settled! There are no outstanding expenses.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    transfers = calculate_settlements(expenses, members)
    if not transfers:
        await update.message.reply_text(
            "🎉 *Everyone is perfectly settled!* Net balance is ₹0 across all roommates.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # 1. Summary of minimum transfers
    summary_lines = ["🤝 *Minimal Settlement Plan:*\n"]
    for t in transfers:
        summary_lines.append(f"• *{t.debtor}* ➔ pays ➔ *{t.creditor}*: *₹{t.amount:.2f}*")

    summary_lines.append("\n🕊️ *Peace Keeper Reminder Drafts:*")
    summary_lines.append("_Polite, non-nagging drafts prepared below. Nothing is sent without approval:_")
    await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)

    # 2. For each transfer, generate a polite reminder draft with [Approve & Send] [Discard]
    for transfer in transfers:
        draft_text = draft_reminder_with_claude(
            debtor=transfer.debtor,
            creditor=transfer.creditor,
            amount=transfer.amount,
        )

        reminder_id = str(uuid.uuid4())[:8]
        PENDING_REMINDERS[reminder_id] = {
            "group_id": group_id,
            "debtor": transfer.debtor,
            "creditor": transfer.creditor,
            "amount": transfer.amount,
            "draft_text": draft_text,
        }

        keyboard = [
            [
                InlineKeyboardButton("🚀 Approve & Send", callback_data=f"appr_rem:{reminder_id}"),
                InlineKeyboardButton("🗑️ Discard", callback_data=f"disc_rem:{reminder_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        card = (
            f"📨 *Draft for {transfer.debtor}* (from {transfer.creditor} for ₹{transfer.amount:.2f}):\n\n"
            f"💬 _{draft_text}_\n\n"
            f"👇 *Human Approval Required:*"
        )
        await update.message.reply_text(card, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear recorded expenses once settled."""
    group_id = get_group_id(update)
    count = storage.clear_expenses(group_id)
    await update.message.reply_text(
        f"🧹 Cleared {count} expense(s). Balances are now reset to ₹0.00!",
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================================
# Natural Language Message & Voice Handlers
# ============================================================================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming natural language expense messages."""
    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    # Check if message looks like an expense or monetary query
    # If it has numbers or expense keywords, parse it
    keywords = ["paid", "spent", "split", "bought", "for", "₹", "rs", "inr"]
    has_digit = any(char.isdigit() for char in text)
    has_keyword = any(kw in text.lower() for kw in keywords)

    if not (has_digit or has_keyword):
        # Ignore casual chatter that has no numbers or expense keywords
        return

    group_id = get_group_id(update)
    sender_name = get_sender_display_name(update)
    known_members = storage.get_members(group_id)

    # Register sender if not yet present
    if sender_name not in known_members:
        storage.add_member(group_id, sender_name, update.effective_user.id if update.effective_user else None)
        known_members = storage.get_members(group_id)

    try:
        parsed: ParsedExpense = parse_expense_with_claude(
            text=text,
            sender_name=sender_name,
            known_members=known_members,
        )
    except ExpenseParseError as e:
        await update.message.reply_text(f"⚠️ {str(e)}", parse_mode=ParseMode.MARKDOWN)
        return
    except Exception as e:
        logger.error(f"Unexpected parsing error: {e}")
        await update.message.reply_text(
            "⚠️ Could not parse expense. Please rephrase with payer, amount, item, and participants.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Present Confirmation Card
    await show_confirmation_card(update, group_id, parsed)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice notes with ElevenLabs Speech-to-Text if API key is present."""
    elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not elevenlabs_key:
        # User requested: "If the key is missing, skip this feature silently."
        return

    voice = update.message.voice
    if not voice:
        return

    status_msg = await update.message.reply_text("🎙️ _Transcribing voice note with ElevenLabs..._", parse_mode=ParseMode.MARKDOWN)

    try:
        # Download voice note audio
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        # ElevenLabs S2T API call
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": elevenlabs_key}
        files = {"file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg")}
        data = {"model_id": "scribe_v1"}

        resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"ElevenLabs S2T error {resp.status_code}: {resp.text}")
            await status_msg.edit_text("⚠️ Could not transcribe audio. Please type the expense in text.")
            return

        result = resp.json()
        transcribed_text = result.get("text", "").strip()

        if not transcribed_text:
            await status_msg.edit_text("⚠️ No speech detected in voice note.")
            return

        await status_msg.edit_text(f"🎙️ *Heard:* \"{transcribed_text}\"", parse_mode=ParseMode.MARKDOWN)

        # Parse transcribed text
        group_id = get_group_id(update)
        sender_name = get_sender_display_name(update)
        known_members = storage.get_members(group_id)

        parsed = parse_expense_with_claude(
            text=transcribed_text,
            sender_name=sender_name,
            known_members=known_members,
        )
        await show_confirmation_card(update, group_id, parsed)

    except Exception as e:
        logger.error(f"Voice note processing error: {e}")
        await status_msg.edit_text("⚠️ Voice transcription error. Please type the expense.")


async def show_confirmation_card(update: Update, group_id: str, parsed: ParsedExpense) -> None:
    """Display interactive confirmation card with Confirm & Cancel buttons."""
    token = str(uuid.uuid4())[:8]
    PENDING_EXPENSES[token] = {
        "group_id": group_id,
        "parsed": parsed,
    }

    per_person = round(parsed.amount / len(parsed.participants), 2)
    participants_str = ", ".join(parsed.participants)

    card_text = (
        "🧾 *Confirm Expense Details*\n\n"
        f"💳 *Payer:* {parsed.payer}\n"
        f"💰 *Total Amount:* ₹{parsed.amount:.2f}\n"
        f"📝 *Description:* {parsed.description}\n"
        f"👥 *Split Between ({len(parsed.participants)}):* {participants_str}\n"
        f"💸 *Share Per Person:* ₹{per_person:.2f}\n\n"
        "_Is this correct? Click Confirm to save to ledger._"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"conf_exp:{token}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"canc_exp:{token}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


# ============================================================================
# Interactive Callback Query Handlers
# ============================================================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button clicks for expense confirmation and reminder approvals."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- 1. Expense Confirmation Flow ---
    if data.startswith("conf_exp:"):
        token = data.split(":", 1)[1]
        pending = PENDING_EXPENSES.pop(token, None)
        if not pending:
            await query.edit_message_text("⚠️ This confirmation has expired or was already handled.")
            return

        parsed: ParsedExpense = pending["parsed"]
        group_id = pending["group_id"]

        expense = Expense(
            group_id=group_id,
            payer=parsed.payer,
            amount=parsed.amount,
            description=parsed.description,
            participants=parsed.participants,
        )
        exp_id = storage.add_expense(expense)

        # Make sure all participants are in group members list
        for p in parsed.participants:
            storage.add_member(group_id, p)

        confirmation_text = (
            f"✅ *Expense #{exp_id} Saved to Ledger!*\n\n"
            f"💳 *{parsed.payer}* paid *₹{parsed.amount:.2f}* for *{parsed.description}*\n"
            f"👥 Split among: {', '.join(parsed.participants)} (₹{expense.share_per_person:.2f} each)\n\n"
            f"Check `/balances` to see updated balance sheet."
        )
        await query.edit_message_text(confirmation_text, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("canc_exp:"):
        token = data.split(":", 1)[1]
        pending = PENDING_EXPENSES.pop(token, None)
        if not pending:
            await query.edit_message_text("❌ Expense was discarded.")
            return

        await query.edit_message_text("❌ *Expense discarded.* Nothing was saved to the ledger.", parse_mode=ParseMode.MARKDOWN)

    # --- 2. Reminder Approval Flow ---
    elif data.startswith("appr_rem:"):
        rem_id = data.split(":", 1)[1]
        reminder = PENDING_REMINDERS.pop(rem_id, None)
        if not reminder:
            await query.edit_message_text("⚠️ This reminder draft has expired.")
            return

        group_id = reminder["group_id"]
        debtor = reminder["debtor"]
        creditor = reminder["creditor"]
        amount = reminder["amount"]
        draft_text = reminder["draft_text"]

        daily_cap = int(os.getenv("DAILY_REMINDER_CAP", "2"))

        # Check daily cap
        if not storage.can_send_reminder(group_id, debtor, daily_cap=daily_cap):
            storage.log_reminder(
                ReminderLog(
                    group_id=group_id,
                    debtor=debtor,
                    creditor=creditor,
                    amount=amount,
                    message=draft_text,
                    status="cap_exceeded",
                )
            )
            await query.edit_message_text(
                f"⚠️ *Daily reminder limit reached for {debtor}* (max {daily_cap} reminders/day).\n"
                f"🛡️ To prevent spamming and maintain peace, this reminder was *not* sent today.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Log approved reminder
        storage.log_reminder(
            ReminderLog(
                group_id=group_id,
                debtor=debtor,
                creditor=creditor,
                amount=amount,
                message=draft_text,
                status="approved",
            )
        )

        sent_count = storage.get_daily_reminder_count(group_id, debtor)

        # Notify the group politely with the approved message!
        approved_post = (
            f"🕊️ *Reminder from {creditor} to {debtor}:*\n\n"
            f"💬 \"{draft_text}\"\n\n"
            f"*(Sent with human approval • Reminder {sent_count}/{daily_cap} today)*"
        )
        await query.edit_message_text(approved_post, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("disc_rem:"):
        rem_id = data.split(":", 1)[1]
        reminder = PENDING_REMINDERS.pop(rem_id, None)
        if reminder:
            storage.log_reminder(
                ReminderLog(
                    group_id=reminder["group_id"],
                    debtor=reminder["debtor"],
                    creditor=reminder["creditor"],
                    amount=reminder["amount"],
                    message=reminder["draft_text"],
                    status="discarded",
                )
            )
        await query.edit_message_text("🗑️ *Reminder draft discarded.* Group was not notified.", parse_mode=ParseMode.MARKDOWN)


# ============================================================================
# Application Entry Point
# ============================================================================

def create_bot_application(token: Optional[str] = None) -> Application:
    """Build and configure the Telegram Bot Application."""
    if token is not None:
        bot_token = token.strip()
    else:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing or empty.")

    app = ApplicationBuilder().token(bot_token).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("members", members_command))
    app.add_handler(CommandHandler("balances", balances_command))
    app.add_handler(CommandHandler("settle", settle_command))
    app.add_handler(CommandHandler("clear", clear_command))

    # Callback queries (buttons)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Voice notes (optional)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    # Natural language messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    return app


def main() -> None:
    """Run bot in polling mode."""
    print("🚀 Starting Roommate Peace Keeper Bot (polling mode)...")
    try:
        app = create_bot_application()
        print("✅ Bot is online and listening for messages. Press Ctrl+C to stop.")
        app.run_polling()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("👉 Please set TELEGRAM_BOT_TOKEN in your .env file.")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")


if __name__ == "__main__":
    main()
