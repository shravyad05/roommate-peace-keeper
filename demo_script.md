# Roommate Peace Keeper — 2-Minute Demo Script ⏱️🕊️

**Ideathon:** wHACKiest 2026 | **Track 1** | **Team Lumen** (ID: `7974a5e3`)  
**College:** Sapthagiri NPS University  
**Presenters:** Shravya.D & Shreya.V.Hegde  

---

## 🎬 Demo Overview (120 Seconds)

| Timestamp | Phase | What to Say / Do | Key Screen Action |
|---|---|---|---|
| **0:00 – 0:20** | **The Hook** | *"Every shared flat has that one awkward conversation: 'Hey, remember that ₹400 from 3 weeks ago?' Splitwise is tedious to open, and Excel sheets turn roommates into accountants. Meet Roommate Peace Keeper — an AI bot in your Telegram group that keeps expenses balanced without ruining friendships."* | Show Telegram group with bot added. |
| **0:20 – 0:50** | **Natural Language Logging** | *"Instead of filling forms, you just chat naturally. Watch this:"*<br>Type: `Paid 600 for dinner, split 3` | Bot shows **Confirmation Card** with Payer, Amount, and Split details. Show clicking **[Confirm]**. |
| **0:50 – 1:15** | **Complex Splits & Net Balances** | *"It handles multi-person splits effortlessly."*<br>Type: `Ravi paid 300 for wifi, split between me, Ravi and Anu`<br>Click **[Confirm]**.<br>Type: `/balances` | Bot displays live **Net Balances**: who is owed (+₹) and who owes (-₹) with green and red indicators. |
| **1:15 – 1:45** | **Smart Settlement & The Approval Gate** | *"Now the magic: `/settle` doesn't just calculate minimum transfers to avoid debt chains — it drafts a polite, non-nagging reminder using Claude.*<br>*Notice the golden rule: **Nothing is sent without human approval**."* | Run `/settle`. Bot shows minimal transfers and Claude draft. Click **[Approve & Send]**. Demonstrate daily cap (max 2/day). |
| **1:45 – 2:00** | **Voice & Closing** | *"Forgot to type? Send an audio voice note — ElevenLabs transcribes it and Claude parses it instantly. Roommate Peace Keeper brings math, empathy, and peace to your shared home."* | Play 5-sec voice sample or recap UPI & Google Sheets roadmap. |

---

## 💬 Sample Messages Cheat Sheet (Copy-Paste Ready)

### 1. Registering Members
```text
/members add Shravya, Shreya, Rohan, Ravi, Anu
```
*Bot responds with verified group roster.*

---

### 2. Logging Expenses (Natural Language)

**Sample 1: Simple 3-way split (Auto-resolves sender as payer)**
```text
Paid 600 for dinner, split 3
```
*Expected Parse:* Payer: `[Sender]`, Amount: `₹600.00`, Item: `Dinner`, Split: 3 roommates (`₹200.00` each).

**Sample 2: Explicit payer with specific roommate names**
```text
Ravi paid 300 for wifi, split between me, Ravi and Anu
```
*Expected Parse:* Payer: `Ravi`, Amount: `₹300.00`, Item: `Wifi`, Split: `[Sender]`, `Ravi`, `Anu` (`₹100.00` each).

**Sample 3: Groceries for the whole apartment**
```text
Shravya paid 1500 for monthly groceries split all
```
*Expected Parse:* Payer: `Shravya`, Amount: `₹1500.00`, Item: `Monthly groceries`, Split: All 5 roommates (`₹300.00` each).

---

### 3. Checking Balances & Settlement

```text
/balances
```
*Shows net creditors (green) and net debtors (red).*

```text
/settle
```
*Calculates minimal transactions (simplifying transitive debts) and displays the AI reminder drafts:*

```text
📨 Draft for Rohan (from Shravya for ₹250.00):
💬 "Hey Rohan! Whenever you get a minute, could you send ₹250.00 for the groceries? No rush, UPI is fine! 😊"
[🚀 Approve & Send]  [🗑️ Discard]
```

Clicking **[Approve & Send]**:
- Validates that daily reminder cap (< 2 today) is intact.
- Sends the polite reminder to the group.
- Increments daily reminder counter in SQLite.

---

## 🛡️ Key Talking Points for Judges

1. **Why not Splitwise?**  
   Splitwise requires everyone to download a separate app, register accounts, and manually tap 8 buttons per bill. Roommate Peace Keeper lives directly inside the chat where roommates already talk.
2. **Why the Approval Gate?**  
   Autonomous bots that ping group chats or DM people create massive anxiety and resentment. With our human-in-the-loop approval gate, you are always in control of what is sent and when.
3. **No Paise Rounding Errors:**  
   Our settlement engine uses integer arithmetic in paise (`total_paise // n` + sequential remainder distribution) so not even 1 paisa is lost across fractional splits (e.g. ₹100 split 3 ways).
4. **Zero-Spam Daily Cap:**  
   Enforced in the database layer. Even if someone taps approve multiple times, roommates cannot be spammed more than twice in 24 hours.
