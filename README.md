# WalletLedger

**A personal-finance assistant that lives in Telegram.** You chat with it like a friend, and it keeps
your books.

> You: *Spent 450 on dinner via Bank*
> Bot: ✅ Expense logged: ₹450.00 → Food & Dining. 🏦 Bank balance: ₹14,550.00

It tracks your accounts (cash, bank, cards), logs spending and income, imports bank/PhonePe PDF
statements, shows reports, and gives savings advice. If you give it an AI key, it also understands
free-form questions. Without one it still works with built-in rules.

New here? Read **[How it works, in plain words](docs/HOW_IT_WORKS.md)** (5 minutes).

## Set it up (3 steps)

```bash
uv sync                                 # 1. install
uv run python scripts/setup.py          # 2. answer a few questions (bot token, your id, optional AI key)
uv run uvicorn main:app --port 8000     # 3. start the bot
```

Then open your bot in Telegram and send `/start`.

- You get the bot token from **@BotFather** in Telegram (`/newbot`).
- The wizard creates `.env`, makes a strong secret key, finds your Telegram id, picks the database
  (a SQLite file by default, no install), tests an AI key if you have one, and publishes the command menu.
- Check that everything is healthy at any time: `uv run python scripts/setup.py --check`
- Needs Python 3.14 and [uv](https://github.com/astral-sh/uv).

## What you can do

| Say or tap | What happens |
|---|---|
| *Paid 150 to Starbucks for coffee* | logs an expense |
| *Received 60000 salary in Bank* | logs income |
| *Transferred 2000 from Bank to Cash* | moves money (not counted as spending) |
| Send a PhonePe / GPay / bank **PDF** | previews and imports the transactions |
| `/balance` · `/report` | your accounts, and the last 30 days of spending |
| `/coach` · `/budgeter` · `/summary` | savings advice in three tones (needs an AI key) |
| `/status` | is AI on, which model, how many keys |
| `/help` | everything, in the chat |

Type `/` in Telegram to see the whole command menu.

## AI keys (all managed in the chat)

There are three layers, tried in this order. If one fails, the next takes over automatically:

1. **Your own key**: `/setkey <key>`. Every key is **tested live before it is saved**, so a dead or
   mistyped key is rejected with the reason. Gemini (`AIza…` and the newer `AQ.…`), OpenAI, Claude and Groq work.
2. **Shared keys** the admin manages for everyone: `/admin addkey <key>`. Stored encrypted.
3. **Keys in `.env`** (`GEMINI_API_KEYS=…`), for people who prefer files.

| Command | What it does |
|---|---|
| `/keys` | numbered, masked list of your keys |
| `/testkey [n]` | re-test one key or all |
| `/editkey <n> <new key>` | replace key n (the old one stays unless the new one works) |
| `/delkey <n>` · `/pausekey <n>` · `/resumekey <n>` | remove, pause, re-enable |
| `/admin` | admin only: manage shared keys, see bot stats |

Model names are discovered automatically from each provider, so nothing needs updating by hand.
Keys are encrypted in the database; the bot also deletes your message after you send a key.

## Settings

Everything lives in `.env` (the wizard fills it in; `.env.example` explains every line).
The ones you will actually touch:

| Setting | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `ALLOWED_CHAT_IDS` | who may use the bot (empty = anyone: set this) |
| `ADMIN_CHAT_IDS` | who may use `/admin` |
| `SECRET_KEY` | encrypts saved AI keys, chat history and notes (the wizard generates it) |
| `DB_MODE` | `sqlite` (default, a single file) or `postgres` (`docker compose up -d`) |

## Protect your data

Chat history, transaction notes and AI keys are encrypted in the database with `SECRET_KEY`.
After upgrading, back up the database, then run `uv run python scripts/protect_data.py encrypt`
once to encrypt older rows (`status` shows progress). The server can still read your data (it has
to, to answer you). What this does and does not protect: [SECURITY.md](docs/SECURITY.md).

## For developers

```bash
uv run python -m unittest discover -s tests    # tests (offline)
uv run python scripts/setup_bot.py --show      # command menu on Telegram vs this code
uv run python scripts/seed_demo_data.py        # demo user with 50 transactions
```

Docs: [How it works](docs/HOW_IT_WORKS.md) · [Architecture diagrams](docs/ARCHITECTURE.md) ·
[Security & data storage](docs/SECURITY.md) · [Deployment](docs/DEPLOYMENT.md) ·
[Code map](docs/DOCUMENTATION.md)

## License and contributors

Apache License 2.0, see [LICENSE](LICENSE). Built by the people in [CONTRIBUTORS.md](CONTRIBUTORS.md).
