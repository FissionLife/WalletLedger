# How WalletLedger works, in plain words

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
3. **The brain** works out what you meant. With an AI key it asks the model; without one it uses
   built-in rules that understand common phrasing. It then picks a *tool*: "log an expense of 450,
   category Food & Dining, account Bank".
4. **The ledger** changes the account balance and saves the transaction in one safe step, or
   refuses with a clear message (for example a negative amount).
5. **The bot replies** with what it did and your new balance.

Big amounts (₹50,000 and up) ask "are you sure?" first, so a typo can't move a fortune.

## Where the AI key comes in

The AI is optional. It makes the bot understand free-form text and write advice in a friendly tone.
When the bot needs the AI it looks for a key in this order:

1. **your own** key (you sent `/setkey`),
2. a **shared** key the admin added for everyone,
3. a key in the server's **`.env`** file.

If a key is wrong, revoked or out of quota, the bot moves to the next one. If there are none left it
carries on in **offline mode** with the built-in rules, so it never just stops. `/status` tells you
which mode you are in.

Keys are tested the moment you add them, and stored encrypted, so even someone who copies the database
file cannot read them without the server's `SECRET_KEY`.

## Where your data lives

In one database: a single SQLite file (`walletledger.db`) by default, or PostgreSQL if you switch
`DB_MODE`. It holds your accounts, transactions, chat history and encrypted AI keys.
**Only the AI keys are encrypted.** Anyone who can read the file can read your transactions, so keep the
file private, use disk encryption, and keep `ALLOWED_CHAT_IDS` set. Details: [SECURITY.md](SECURITY.md).

## Who can use the bot

Telegram proves who is sending a message, and WalletLedger keys all data to that Telegram chat id.
`ALLOWED_CHAT_IDS` is the guest list; `ADMIN_CHAT_IDS` is who can manage shared AI keys.
The setup wizard fills in both with your own id.

## The pieces, in one line each

| File | Job |
|---|---|
| `app/bot/telegram.py` | talks to Telegram (receives messages, sends replies, the command menu) |
| `app/bot/main.py` | commands, PDF import, who-is-allowed checks |
| `app/bot/agent.py` | the brain: understands the message and picks tools |
| `app/bot/keys.py` | `/setkey`, `/keys`, `/admin` and friends |
| `app/services_ai/ai_gateway.py` | calls the AI models; key rotation and fallback; tests keys |
| `app/services_ai/mcp_server.py` | the tools the brain can use (log expense, transfer, report, …) |
| `app/services/ledger.py` | the only code that changes balances |
| `app/models.py`, `app/db.py` | the database |
| `scripts/setup.py` | the setup wizard and health check |
