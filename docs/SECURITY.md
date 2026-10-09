# Data Storage and Security

Honest summary: **only users' LLM API keys are encrypted. Balances, transactions, merchants and the
full chat history are stored as plain text in the database.** Anyone who can read the database file,
the server disk or a backup can read all of it. This page lists what is stored, who can see it, and
how to harden it.

## 1. What is stored where

| Data | Where | Protected? |
|---|---|---|
| Telegram chat id (the user's identity) | `users.telegram_chat_id` | plain text |
| Account names and balances | `accounts` | plain text |
| Transactions (amount, merchant, description, date) | `transactions`, `merchants`, `categories` | plain text |
| **Conversation history** (everything users type and the bot says) | `chat_messages` (permanent; last 20 are sent to the LLM as context) | plain text. API keys are redacted before saving |
| User LLM API keys | `api_keys.encrypted_key` | Fernet (AES + HMAC) |
| Server-side fallback LLM keys, bot token, `SECRET_KEY` | environment / `.env` | file permissions only |

The default database is a file, `walletledger.db`. It is git-ignored but is an ordinary file: anyone
who copies it can open it with a SQLite viewer.

## 2. Authentication: how identity works

There are no passwords or logins. **Identity = Telegram chat id**, and all data is keyed to it.

- Over Telegram this is reasonable: Telegram authenticates the person. The risk is the path *to*
  your server, not Telegram itself.
- **Webhook:** requests are checked against Telegram's secret-token header whenever the bot is
  running in webhook mode. The secret is `TELEGRAM_WEBHOOK_SECRET`, or, if unset, derived from the
  bot token. Set an explicit random one.
- **`/bot/simulate_chat` and the token-less `/bot/webhook`** let the caller act as *any* chat id.
  They are enabled automatically only while **no bot token is configured** (local dev). When a token
  is set they return 404 unless you explicitly set `ENABLE_DEV_ENDPOINTS=true`. Never enable them on
  a reachable server.
- **Private bot:** set `ALLOWED_CHAT_IDS=123,456` to restrict the bot to specific people. Empty means
  anyone who finds the bot can create an account.
- Telegram chats are encrypted client-to-server only, not end-to-end. Telegram can read messages.
- There are no REST endpoints that return user data; all access is through the bot.

## 3. Can someone hack in and read the data?

| Attacker | Can they read financial data? |
|---|---|
| Random person on the internet | Not through the API: no endpoint returns data without a valid Telegram-signed request, as long as a bot token is set and dev endpoints are off. |
| Another Telegram user | Only their own data (queries filter by `user_id`; covered by a test). With `ALLOWED_CHAT_IDS` they cannot use the bot at all. |
| Someone with the `.db` file, a backup or server disk | **Yes, everything except API keys**, including all past conversations. |
| Someone who also gets `.env` | **Yes, including API keys** (they have `SECRET_KEY`). |
| Someone with the bot token | Can impersonate the bot and read messages sent to it; cannot read your database. Revoke in BotFather if leaked. |
| You / the server operator | Yes. This is not a zero-knowledge design. |
| The LLM provider | Receives what the agent sends: recent chat history, balances and spending summaries, for the key that made the call. |
| Someone reading Telegram history | Anything users typed stays there. API keys sent in chat are redacted in the database, and the bot tries to delete the message, but tell users to check. |

Known software gaps: money is stored as floats (rounded to 2 decimals), there is no rate limiting,
no database migrations, and confirmation state is held in process memory (use one worker).

## 4. How the API keys are encrypted

Keys are encrypted with Fernet (AES-128-CBC plus an HMAC-SHA256 integrity tag, random IV) in
[ai_gateway.py](../app/services_ai/ai_gateway.py). The Fernet key is `sha256(SECRET_KEY)`.
Tampered or wrong-key data fails to decrypt instead of returning garbage.

- Use a long random `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  The built-in default is public in the repo; the app warns at startup if you keep it.
- Because the key is a plain SHA-256 of `SECRET_KEY` (no salt or slow KDF), a weak or guessable
  `SECRET_KEY` can be brute-forced by anyone holding the database. Random 48+ characters avoids that.
- **Never change `SECRET_KEY` casually**: stored user keys become unreadable (users re-add them).
  There is no rotation support yet; adding `MultiFernet` with a list of old keys is the fix.
- Keep `SECRET_KEY` somewhere other than the database host/backups, otherwise the encryption adds
  little.

## 5. How to protect the rest of the data (recommended order)

1. **Disk / volume encryption** (BitLocker, LUKS, encrypted cloud volumes). Cheapest big win; covers
   the database, backups and swap.
2. **Postgres in production** (docker-compose is provided) with TLS (`?sslmode=require`), a
   least-privilege user, a private network and encrypted backups. Never expose the DB port.
3. **Secrets:** never commit `.env`, restrict its permissions, prefer your host's secret manager.
4. **HTTPS only** behind a reverse proxy; explicit `TELEGRAM_WEBHOOK_SECRET`; dev endpoints off;
   `ALLOWED_CHAT_IDS` set for a personal bot.
5. **Field-level encryption** of the most sensitive columns (chat message `content`, transaction
   `description`, merchant names) with the same Fernet helper via a SQLAlchemy `TypeDecorator`.
   Trade-off: no SQL search or aggregation on those columns. Balances and amounts are used in
   `SUM`/comparisons, so they are not realistic targets. This protects against a stolen DB file, not
   a compromised running server. Chat history is the biggest unencrypted exposure and the best first
   target.
6. **Retention:** limit how long `chat_messages` are kept, add a `/deleteme` command that deletes a
   user (the schema cascades), and avoid logging message bodies.
7. **Per-user keys (strongest):** derive each user's key from a secret only they hold. Even you
   cannot read their data, but the bot cannot work while they are offline and a lost secret means
   lost data. A product decision, not a quick fix.
8. **Monitoring:** alert on repeated 403s at the webhook; keep dependencies updated.

## 6. Pre-deploy checklist

- [ ] `SECRET_KEY` random 48+ chars, stored outside the repo
- [ ] `TELEGRAM_WEBHOOK_SECRET` set (webhook mode only behind HTTPS)
- [ ] `ENABLE_DEV_ENDPOINTS` unset or `false` while a bot token is configured
- [ ] `ALLOWED_CHAT_IDS` set if the bot is personal/private
- [ ] Postgres with TLS, or SQLite on an encrypted volume
- [ ] `.env` and `*.db` not in git and not world-readable
- [ ] Encrypted backups
- [ ] Users told: delete any message containing an API key
