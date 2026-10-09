# Deployment Guide

See [.env.example](.env.example) for every setting and [docs/SECURITY.md](docs/SECURITY.md) for the
hardening checklist.

## 1. Local (SQLite + Telegram polling)

```bash
uv sync
cp .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY
# put TELEGRAM_BOT_TOKEN (from @BotFather) and SECRET_KEY into .env
uv run uvicorn main:app --port 8000
```

With `USE_WEBHOOK=false` the app long-polls Telegram, so no public URL is needed. Message your bot
`/start`. Without a bot token, set `ENABLE_DEV_ENDPOINTS=true` and use `POST /bot/simulate_chat`.

Optional demo data: `uv run python scripts/seed_demo_data.py` (chat id `demo`).

## 2. Production (Postgres + webhook)

1. Provision Postgres with TLS and a least-privilege user. Set
   `DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/walletledger?sslmode=require`.
2. Put the app behind an HTTPS reverse proxy (Caddy, nginx, a cloud load balancer).
3. Set: `USE_WEBHOOK=true`, `WEBHOOK_URL=https://your-domain/bot/webhook`, `WEBHOOK_SECRET`
   (`python -c "import secrets; print(secrets.token_hex(32))"`), `SECRET_KEY`, `TELEGRAM_BOT_TOKEN`,
   and `ALLOWED_CHAT_IDS` for a private bot. Keep `ENABLE_DEV_ENDPOINTS=false`.
4. Run: `uv run uvicorn main:app --host 0.0.0.0 --port 8000` (one worker: confirmations and persona
   mode are held in process memory).
5. On startup the app registers the webhook with Telegram. Check `GET /health`.

Tables are created automatically at startup (`create_all`). There is no migration tool yet, so
schema changes to existing databases need manual SQL or adding Alembic.

## 3. Operations
- **Backups:** back up the database; encrypt them. Keep `SECRET_KEY` separately, since stored user API
  keys cannot be decrypted without it.
- **Key rotation:** move the old `SECRET_KEY` into `SECRET_KEY_OLD`, set a new `SECRET_KEY`.
- **Tests:** `uv run python -m unittest discover -s tests` (also run in CI).
- **Troubleshooting:** bot silent -> check the token and that only one poller or webhook is active;
  403 on the webhook -> `WEBHOOK_SECRET` mismatch; "Cannot decrypt" warnings -> wrong `SECRET_KEY`.
