# Deployment

## On your own computer (simplest)

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

The very first start asks a few questions (bot token, your id, optional AI key) and then keeps starting;
after that it starts straight away. To change an answer later run `uv run python scripts/setup.py`.
It never asks when nobody can answer (Docker, a service, CI): there it prints what is missing and starts
anyway, so give it `TELEGRAM_BOT_TOKEN` and `SECRET_KEY` as environment variables, or run
`uv run python scripts/setup.py --defaults --token <token>` once to write `.env` without questions.

The bot uses **long polling**: it asks Telegram for new messages, so you need no public address and no
open ports. The database is a single SQLite file (`walletledger.db`). Stop with `Ctrl+C`.
Run only **one** copy at a time (two copies polling the same bot fight each other).

Check health: `uv run python scripts/setup.py --check` or `curl localhost:8000/health`.

## On a server (always on)

1. Copy the project to the server and run `uv sync`, then `uv run python scripts/setup.py --defaults --token <token>` (or set the environment variables).
2. Keep it running with your platform's process manager (systemd, Docker, a PaaS "worker"):
   `uv run uvicorn main:app --host 0.0.0.0 --port 8000`
3. Keep `walletledger.db` on a disk that is backed up, or switch to Postgres (below).

### Webhook mode (no polling)

Telegram can push messages to your server instead. This is the mode that suits serverless and
scale-to-zero hosts (Cloud Run, Fly.io, Render). It needs a public **HTTPS** address.

```
USE_WEBHOOK=true
WEBHOOK_URL=https://your-domain.example/bot/webhook
TELEGRAM_WEBHOOK_SECRET=<long random string>      # optional; derived from the token if empty
```

The server registers the webhook with Telegram on start. On a scale-to-zero host, use **Postgres**
(not SQLite), because the local disk disappears when the instance stops.

### Several bots, one backend

Put extra tokens in `TELEGRAM_BOT_TOKENS` (comma-separated, each from its own @BotFather chat) next to
`TELEGRAM_BOT_TOKEN`. One server, one database and one set of AI keys then serve all of them: separate
bots for separate teams, a demo bot next to the real one, or a rename without losing users.

- **Same person, same ledger.** Data follows the Telegram chat id, so someone who talks to two of your
  bots sees one set of accounts and transactions. (Two different people never share anything.)
- **Polling** needs nothing else. **Webhooks**: each bot gets its own address, `WEBHOOK_URL/<bot id>`
  (a single bot keeps `WEBHOOK_URL` exactly as before), and its own secret unless you set
  `TELEGRAM_WEBHOOK_SECRET`, which is then shared.
- `scripts/setup_bot.py` publishes the command menu to every bot, and the dashboard Mini App signs in from
  whichever bot opened it.
- `ALLOWED_CHAT_IDS` and `ADMIN_CHAT_IDS` apply to all of them. There are no per-bot rules.

### Docker / serverless hosts

A `Dockerfile` is included, so any host that runs containers works (Google Cloud Run, Fly.io, Render,
Railway, a plain VPS):

```bash
docker build -t walletledger .
docker run -p 8080:8080 --env-file .env walletledger
```

For a scale-to-zero host (it sleeps when nobody is chatting), set:

```
USE_WEBHOOK=true
WEBHOOK_URL=https://<your-service-url>/bot/webhook
DB_MODE=postgres            # a hosted Postgres (Neon, Supabase, Cloud SQL, ...), not a local file
POSTGRES_HOST=...  POSTGRES_USER=...  POSTGRES_PASSWORD=...  POSTGRES_DB=...
PUBLIC_URL=https://<your-service-url>
SECRET_KEY=<the same value every time>
```

Put those in the host's secret settings rather than in a file. Telegram wakes the service with each
message, so nothing runs (or costs) while the chat is quiet.

### Cloudflare (tunnel or Containers)

One command gives you an https address for the dashboard (`scripts/tunnel.py`); Cloudflare Containers can
host the Docker image itself. Plain Workers cannot run this app. See [CLOUDFLARE.md](CLOUDFLARE.md).

### Dashboard link and Telegram Mini App

`/dashboard` sends a private link that expires (`DASHBOARD_LINK_MINUTES`, default 2 hours).
Without `PUBLIC_URL` the link points at `http://localhost:8000` and opens in a browser on the same
computer. Set `PUBLIC_URL` to an **https** address and the same button opens inside Telegram as a
Mini App. For a quick demo from a laptop, a tunnel gives you that address with no hosting:

```bash
uv run python scripts/tunnel.py                    # starts the tunnel and the server, sets PUBLIC_URL for you
```

The address changes every run. For a fixed one, use your own tunnel and put it in `PUBLIC_URL`
([CLOUDFLARE.md](CLOUDFLARE.md)). Nothing else to configure: `/dashboard` sends a button that opens the
page inside Telegram.

### PostgreSQL

```bash
docker compose up -d        # Postgres 16 on localhost:5433
```

then set `DB_MODE=postgres` in `.env` (the `POSTGRES_*` values already match `docker-compose.yml`).
Tables are created automatically on start.

## Before you let other people in

- `ALLOWED_CHAT_IDS` set to the people who may use the bot.
- `ADMIN_CHAT_IDS` set to you.
- `SECRET_KEY` generated (the wizard does it). Never change it later without keeping the old one in
  `SECRET_KEY_OLD`, or saved AI keys stop working.
- Back up the database. See [SECURITY.md](SECURITY.md) for what is and isn't encrypted.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "address already in use" | another copy is running; stop it or use `--port 8001` |
| Bot silent | `setup.py --check`; only one copy running? token correct? |
| "Conflict: terminated by other getUpdates" | two copies are polling the same bot |
| Bot answers but never uses AI | `/status` in the chat shows why; add a key with `/setkey` |
