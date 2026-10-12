# WalletLedger

**A personal-finance assistant that lives in Telegram.** You chat with it like a friend, and it keeps
your books.

> You: *Spent 450 on dinner via Bank*
> Bot: 💸 −₹450 · Food & Dining
> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Bank ₹84,550 &nbsp;&nbsp; [↩️ Undo]

It tracks your accounts (cash, bank, cards), logs spending and income, imports PhonePe / GPay / Paytm /
BHIM / bank PDF statements, draws charts, opens a web dashboard, and plans savings goals. Clear messages
are understood by built-in rules (instant, no AI needed). Add your own AI key and it also handles
free-form questions like *"can I afford a ₹50,000 laptop in 5 months?"*.

New here? Read **[How it works, in plain words](docs/HOW_IT_WORKS.md)** (5 minutes).
Showing it to someone? Follow the **[demo script](docs/DEMO.md)**.

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
| *Spent 200 on chai, 80 on auto* | logs both (any number of items, dates like "yesterday" work) |
| *Received 60000 salary in Bank* | logs income |
| *Transferred 2000 from Bank to Cash* | moves money (not counted as spending) |
| Send a PhonePe / GPay / Paytm / BHIM / bank **PDF** | previews, then imports with the right dates |
| `/balance` | your accounts and total money |
| `/stats` · `/stats 90d food` · `/stats last month` | numbers, a chart, and buttons to switch period or chart |
| `/chart categories` | pick from 13 chart types (trend, weekday, heatmap, merchants, net worth, …) |
| `/history` · `/undo` | recent entries; take back the last one (or tap ↩️ Undo) |
| `/budget food 6000` | monthly budgets with warnings as you near them |
| `/plan 50000 6` or *I want to save 50k in 6 months* | is it realistic from your real income and spending, and what to trim |
| `/dashboard` | your web dashboard: 12 interactive charts, filters, a transactions table |
| `/export` | download your data as CSV |
| `/coach` · `/budgeter` · `/summary` | savings advice in three tones (needs an AI key) |
| `/status` · `/help` | AI and storage health; everything, in the chat |

Type `/` in Telegram to see the command menu. Questions are never logged as spending: *"is 640 too much
for dinner?"* gets an answer, not a ₹640 entry.

## AI keys (bring your own)

**By default every user brings their own key**, so there is no shared bill. Keys are tried in this order,
and if one fails the next takes over automatically:

1. **Your own key**: `/setkey <key>`. It is **tested live before it is saved**, so a dead or mistyped key
   is rejected with the reason. Supported: **Gemini** (`AIza…` and the newer `AQ.…`), **OpenAI**,
   **Claude**, **Groq**, **OpenRouter**, **xAI Grok**, **DeepSeek**, **Mistral**
   (`/setkey mistral <key>`, since Mistral keys have no recognisable start). Free Gemini key:
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. **Shared keys** the admin chooses to provide: `/admin addkey <key>`. Stored encrypted. Optional.
3. **Keys in `.env`** (`GEMINI_API_KEYS=…`), for people who prefer files. Optional.

| Command | What it does |
|---|---|
| `/keys` | numbered, masked list of your keys, with buttons |
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
| `PUBLIC_URL` | optional https address; makes `/dashboard` open inside Telegram as a Mini App |

## Cloudflare

`uv run python scripts/tunnel.py` starts a free Cloudflare Tunnel and the server together, so
`/dashboard` opens inside Telegram (needs the `cloudflared` program; install hints are printed).
Hosting the whole app on Cloudflare is possible with **Cloudflare Containers** (scaffolding in
[`cloudflare/`](cloudflare/)); plain Workers cannot run this Python app. All options, with the reasons:
[docs/CLOUDFLARE.md](docs/CLOUDFLARE.md).

## Protect your data

Chat history, transaction notes and AI keys are encrypted in the database with `SECRET_KEY`.
After upgrading, back up the database, then run `uv run python scripts/protect_data.py encrypt`
once to encrypt older rows (`status` shows progress). The server can still read your data (it has
to, to answer you). What this does and does not protect: [SECURITY.md](docs/SECURITY.md).

## For developers

```bash
uv run python -m unittest discover -s tests    # tests (offline, never touch your .env)
uv run python scripts/setup_bot.py --show      # command menu on Telegram vs this code
uv run python scripts/setup_bot.py             # publish the menu, description and menu button
uv run python scripts/seed_demo_data.py --chat-id <your id>   # 90 days of demo data
uv run python scripts/inspect_statement.py file.pdf --text    # see how a statement PDF is read
```

**New to the code?** Open the [interactive explorer](https://fissionlife.github.io/WalletLedger/explore/) (guided tours, a clickable map, search), or read [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md), a one-page index.

Docs: **[Project guide: what is where and how it works](docs/PROJECT_GUIDE.md)** ·
[How it works](docs/HOW_IT_WORKS.md) · [Demo script](docs/DEMO.md) ·
[Architecture diagrams](docs/ARCHITECTURE.md) · [Security & data storage](docs/SECURITY.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Code map](docs/DOCUMENTATION.md)

## License and contributors

Apache License 2.0, see [LICENSE](LICENSE). Built by the people in [CONTRIBUTORS.md](CONTRIBUTORS.md).
