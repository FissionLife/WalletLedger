# How WalletLedger works, in plain words

*Short version. The full tour of the code, the data and the encryption is the [project guide](PROJECT_GUIDE.md).*

## The idea

Most expense apps ask you to open the app, pick a category, type an amount. WalletLedger lets you just
*say* it in Telegram, the app you already have open all day.

## The money model: a tank with pipes

- Your **accounts** (Cash, Bank, a wallet, a credit card) are the **pipes that hold money**.
- Everything together is your **tank**: your total money.
- **Spending** takes money out of an account and puts it into a category (Food, Transport, …).
- **Income** puts money into an account.
- A **transfer** just moves money from one of your accounts to another. It is *not* spending, so
  moving money from Bank to Cash never makes your expenses look bigger.

## What happens when you send a message

```
You (Telegram) ──► the bot ──► the "brain" ──► the ledger (database)
                                  │
                                  └─► an AI model, only if you added a key
```

1. **You send a message**: "Spent 450 on dinner via Bank".
2. **The bot** checks you are allowed to use it, handles fixed commands like `/balance` itself, and
   passes everything else to the brain.
3. **The brain** works out what you meant, **rules first**:
   - a clear message ("Spent 200 on chai, 80 on auto") is understood by built-in rules: instant,
     free, no AI call;
   - a question or goal ("can I afford a ₹50,000 laptop in 5 months?") goes to the AI, which may look
     things up and act in a few steps (see below);
   - anything the rules can't read, with no AI key, gets a short hint instead of a guess.
   Either way it ends up choosing a *tool*: "log an expense of 450, category Food & Dining, account Bank".
4. **The ledger** changes the account balance and saves the transaction in one safe step, or
   refuses with a clear message (for example a negative amount).
5. **The bot replies** in two lines, with an **↩️ Undo** button:
   `💸 −₹450 · Food & Dining` / `Bank ₹84,550`.

**First contact.** A new user is asked one question with buttons (Bank, Cash, UPI, Card): where do you
usually pay from? That becomes the default account for anything that names none ("chai 20"), and the bot
then offers to record what is in it now. Nothing blocks: ignore the question and the bot picks Bank and
carries on. Change it any time ("use cash by default"), or fix a balance in words ("bank balance is 25000").
Corrections work in words too: "oops the dinner was actually 540", "delete the coffee".

Big transfers (₹5,000 and up) ask "are you sure?" first, so a typo can't move a fortune.
A message that is a **question** ("is 640 too much for dinner?") is never logged as spending.

## Charts, stats and the dashboard

`/stats` turns your ledger into numbers and a chart picture (matplotlib), with buttons to change the
period (7 days, month, 90 days, …) or the chart. `/dashboard` sends a private, expiring link to a web
page with 12 interactive charts, filters and a transactions table. The link is signed (HMAC) and times
out; inside Telegram it opens as a Mini App and Telegram itself proves who you are.

## Complex questions: one loop, four jobs

For goals and "how am I doing" questions, the AI runs a short loop (`app/bot/orchestrator.py`):

```
AI picks tools  →  we run them  →  AI reads the results  →  repeat (max 5 rounds)  →  plain answer
```

It plays four small roles: **Ledger** (records things exactly as said), **Analyst** (reads your real
numbers first), **Planner** (savings plans) and **Writer** (short friendly answer). The guard rails
are simple: it can only use our tools, it can never touch API keys, a big transfer still waits for
your Yes, and if the AI fails the bot falls back to the simple path. `/plan 50000 6` does the same
maths without any AI: it compares what you need per month with what you really keep.

## Where the AI key comes in

The AI is optional. It makes the bot understand free-form text and write advice in a friendly tone.
**Everyone brings their own key by default** (Gemini, OpenAI, Claude, Groq, OpenRouter, Grok,
DeepSeek or Mistral). When the bot needs the AI it looks for a key in this order:

1. **your own** key (you sent `/setkey`),
2. a **shared** key the admin chose to provide for everyone (optional),
3. a key in the server's **`.env`** file (optional).

If a key is wrong, revoked or out of quota, the bot moves to the next one. If there are none left it
carries on in **offline mode** with the built-in rules, so it never just stops. `/status` tells you
which mode you are in.

Keys are tested the moment you add them, and stored encrypted, so even someone who copies the database
file cannot read them without the server's `SECRET_KEY`.

## Where your data lives

In one database: a single SQLite file (`walletledger.db`) by default, or PostgreSQL if you switch
`DB_MODE`. It holds your accounts, transactions, chat history and AI keys.
**Chat history, transaction notes and AI keys are encrypted** with the server's `SECRET_KEY`. Amounts,
dates, account, category and merchant names are not (the database needs them to add things up), and
the server itself can read everything. Keep the file private, use disk encryption, and keep
`ALLOWED_CHAT_IDS` set. Details: [SECURITY.md](SECURITY.md).

## Who can use the bot

Telegram proves who is sending a message, and WalletLedger keys all data to that Telegram chat id.
`ALLOWED_CHAT_IDS` is the guest list; `ADMIN_CHAT_IDS` is who can manage shared AI keys.
The setup wizard fills in both with your own id.

## The pieces, in one line each

| File | Job |
|---|---|
| `app/bot/telegram.py` | talks to Telegram (receives messages, sends replies, the command menu) |
| `app/bot/main.py` | commands, PDF import, who-is-allowed checks |
| `app/bot/nlu.py` | the rules that read "Spent 200 on chai, 80 on auto" (no AI) |
| `app/bot/agent.py` | the brain: understands the message and picks tools |
| `app/bot/orchestrator.py` | the multi-step loop for goals and questions |
| `app/bot/views.py`, `ui.py`, `replies.py` | stats, charts, buttons and the short replies |
| `app/services/analytics.py`, `app/charts.py` | the numbers and the chart pictures |
| `app/web/` | the web dashboard and Telegram Mini App |
| `app/bot/keys.py` | `/setkey`, `/keys`, `/admin` and friends |
| `app/services_ai/ai_gateway.py` | calls the AI models; key rotation and fallback; tests keys |
| `app/services_ai/mcp_server.py` | the tools the brain can use (log expense, transfer, report, …) |
| `app/services/ledger.py` | the only code that changes balances |
| `app/models.py`, `app/db.py` | the database |
| `app/setup_wizard.py` | the setup questions (asked on first start) and the health check |
