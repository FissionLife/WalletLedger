# Data Storage and Security

Honest summary: **today only users' LLM API keys are encrypted. Balances, transactions, merchants
and descriptions are stored in plain text in the database.** Anyone who can read the database file
(or the server disk, or a backup) can read all financial data. Below is what is stored, who can see
it, and how to harden it.

## 1. What is stored where

| Data | Where | Protected? |
|---|---|---|
| Telegram chat id (the user's identity) | `users.telegram_chat_id` | plain text |
| Account names and balances | `accounts` | plain text |
| Transactions (amount, merchant, description, date) | `transactions`, `merchants`, `categories` | plain text |
| User LLM API keys | `api_keys.encrypted_key` | **Fernet (AES + HMAC)**, key derived from `SECRET_KEY` |
| Bot token, `SECRET_KEY`, webhook secret | `.env` / environment | file permissions only |
| Conversation history | **not stored** (only the resulting transactions). Pending confirmations and mode live in process memory | n/a |

The default database is a file, `walletledger.db`, in the project folder. It is git-ignored, but it
is an ordinary file: copy it and open it with any SQLite viewer.

## 2. Authentication: how identity works

There are no passwords or logins. **Identity = Telegram chat id**, and everything is keyed to it.

- Over Telegram this is reasonable: Telegram authenticates the person, and only they can message as
  that chat id. The risk is the path *to* your server, not Telegram.
- **Webhook:** anyone who knows the URL could POST a fake update claiming any `chat.id`. Defence:
  set `WEBHOOK_SECRET` (checked against Telegram's `X-Telegram-Bot-Api-Secret-Token`, constant-time).
  Without it the webhook is open. Startup logs a warning.
- **`/bot/simulate_chat`:** lets the caller act as *any* chat id. It is now **off by default**
  (`ENABLE_DEV_ENDPOINTS=false`). Never enable it on a reachable server.
- **Private bot:** set `ALLOWED_CHAT_IDS=123,456` to restrict the bot to specific people. Empty
  means anyone who finds the bot can create an account.
- Telegram chats are encrypted client-to-server only, not end-to-end. Telegram can read messages.
- There is no per-request user session, so there is no admin or API layer to attack beyond the
  endpoints in the diagram. There are no REST endpoints that return user data.

## 3. Can someone hack in and read the data?

| Attacker | Can they read financial data? |
|---|---|
| Random person on the internet | Not through the API if `WEBHOOK_SECRET` is set and dev endpoints are off. There is no endpoint that returns data to an unauthenticated caller. |
| Another Telegram user | Only their own data (queries are filtered by `user_id`; covered by a test). With `ALLOWED_CHAT_IDS` they cannot use the bot at all. |
| Someone with the `.db` file, a backup, or server disk access | **Yes, everything except API keys.** |
| Someone who also gets `.env` | **Yes, including API keys** (they have `SECRET_KEY`). |
| Someone with the bot token | Can impersonate the bot and read messages sent to it; cannot read your database. Rotate in BotFather if leaked. |
| The server operator / you | Yes. This is not a zero-knowledge design. |
| The LLM provider | Only data you send. When a user has a key, balances and spending summaries are placed in prompts and go to that provider (Google/OpenAI/etc.) under their terms. |
| Someone reading logs | Logs avoid message text, but Telegram message history itself contains anything users typed, including API keys sent with `/setkey`. Tell users to delete that message. |

Known software gaps: no rate limiting, SQL access is via SQLAlchemy parameters (no raw SQL, so
injection risk is low), amounts are floats, and the in-memory state is per process.

## 4. How the API keys are encrypted

`encrypt_secret` in [vault.py](../app/services_ai/vault.py) uses Fernet (AES-128-CBC with an
HMAC-SHA256 integrity tag, random IV). The Fernet key is derived from `SECRET_KEY` with HKDF.
Tampered or wrong-key data fails to decrypt instead of returning garbage.

- Use a long random `SECRET_KEY`, for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  The built-in default is public in the repo; the app warns at startup if you keep it.
- **Rotation:** set the new value in `SECRET_KEY` and the old one in `SECRET_KEY_OLD`. Old rows keep
  working; re-save keys to re-encrypt them.
- If `SECRET_KEY` is lost, stored API keys are unrecoverable (users just re-add them).
- Keep `SECRET_KEY` out of the database host/backups (separate secret store), otherwise encrypting
  there adds little.

## 5. How to protect the rest of the data (recommended order)

1. **Disk / volume encryption** (BitLocker on Windows, LUKS on Linux, encrypted cloud volumes).
   Cheapest big win; covers the DB file, backups and swap.
2. **Use Postgres in production** with TLS (`?sslmode=require`), a least-privilege DB user, a private
   network, and encrypted backups. Do not expose the DB port.
3. **Lock down secrets:** never commit `.env`, restrict file permissions, use your host's secret
   manager (Docker/K8s secrets, AWS/GCP/Azure secret manager, Doppler, Vault).
4. **Serve over HTTPS only** behind a reverse proxy; set `WEBHOOK_SECRET`; keep
   `ENABLE_DEV_ENDPOINTS=false`; set `ALLOWED_CHAT_IDS` for private use.
5. **Field-level encryption** for the most sensitive columns (descriptions, merchant names,
   balances) using the same Fernet helper, via a SQLAlchemy `TypeDecorator`. Trade-off: you can no
   longer do SQL `SUM`/`WHERE` on encrypted fields, and balances are numeric columns used in
   aggregation, so descriptions/merchants are the realistic targets. This protects against a stolen
   DB file but not against a compromised running server.
6. **SQLite at-rest encryption** if you stay on SQLite: SQLCipher (needs a different driver) or just
   volume encryption.
7. **Per-user keys (strongest):** derive each user's key from a secret only they hold. Then even you
   cannot read their data, but the bot cannot process messages while they are offline and key loss
   means data loss. This is a product decision, not a quick fix.
8. **Backups and retention:** encrypt backups, add a `/deleteme` command to wipe a user's rows
   (the schema already cascades deletes), and avoid logging message bodies.
9. **Monitoring:** alert on repeated 403s at the webhook, and keep dependencies updated.

## 6. Pre-deploy checklist

- [ ] `SECRET_KEY` set to a random 48+ char value, stored outside the repo
- [ ] `WEBHOOK_SECRET` set; `USE_WEBHOOK=true` only behind HTTPS
- [ ] `ENABLE_DEV_ENDPOINTS=false` (default)
- [ ] `ALLOWED_CHAT_IDS` set if the bot is personal/private
- [ ] Postgres with TLS, or SQLite on an encrypted volume
- [ ] `.env` and `*.db` not in git (already in `.gitignore`) and not world-readable
- [ ] Encrypted backups
- [ ] Users told: delete the `/setkey` message after sending it
