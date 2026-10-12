# Data Storage and Security

Honest summary: **chat history, transaction notes and users' AI keys are encrypted in the database.
Amounts, dates, balances and account / category / merchant names are not.** The encryption key is
derived from the server's `SECRET_KEY`, so it protects a copied database file or backup, not a
running server, and **not against the operator**: whoever runs the server and has `SECRET_KEY` can
read everyone's data. The bot has to read your data to answer you, so true "even the operator can't
read it" protection is not possible without breaking the product (see "Private mode" below).

## 1. What is stored where

| Data | Where | At rest |
|---|---|---|
| **Conversation history** (everything users type and the bot says) | `chat_messages.content` | **encrypted** (field key). API keys are also redacted before saving |
| **Transaction notes** (free text) | `transactions.description` | **encrypted** (field key) |
| User and shared AI keys | `api_keys.encrypted_key` | **encrypted** (vault key) |
| Amounts, dates, transaction type, source | `transactions` | plain text, see below |
| Account names and balances | `accounts` | plain text, see below |
| Category names and budgets, merchant names | `categories`, `merchants` | plain text, see below |
| Telegram chat id (the user's identity) | `users.telegram_chat_id` | plain text (needed to find the user) |
| Bot token, server AI keys, `SECRET_KEY` | environment / `.env` | file permissions only |

**Why some columns stay plain text.** The database adds up amounts (`SUM`), filters by date,
groups by category and merchant, and joins tables on ids. It can only do that with values it can
read. Encrypted values are also different every time (random IV), so even "equal to" does not work
on them. Encrypting those columns would mean loading every row into Python for every report: slow,
complex, and still readable by the server. So we encrypt the free text people type, which is the
most personal part ("dinner with my ex", "loan to Ravi for rent", "my salary is ..."), and leave
the numbers and labels the database needs.

The default (`DB_MODE=sqlite`) is a file, `walletledger.db` (`DB_MODE=postgres` uses a server). It
is git-ignored but is an ordinary file: anyone who copies it can open it with a SQLite viewer and
see the plain-text columns above.

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
- **Web dashboard:** the only web endpoints that return user data (`/api/dashboard`,
  `/api/transactions`, `/api/export.csv`). Access needs a **signed, expiring token** that the bot sends
  only to the chat it belongs to (`/dashboard`). The token holds the chat id and an expiry, signed
  with HMAC-SHA256 using a key derived from `SECRET_KEY`, so nobody can forge one for another person.
  Links expire after `DASHBOARD_LINK_MINUTES` (default 2 hours). The API reads the token from a
  header only (never a query string), responses are `no-store`, pages send a strict
  Content-Security-Policy and `no-referrer`, and requests are rate-limited. Inside Telegram (Mini App)
  the server instead verifies Telegram's own signed sign-in data. Anyone who is *sent* a link can open
  it until it expires, so do not forward it. Using `https` (`PUBLIC_URL`) keeps links from being read
  in transit.
- **Placeholder key on a public address:** dashboard links are signed with `SECRET_KEY`, so a published
  placeholder would let anyone sign a link for any chat id. The server therefore **refuses to start** when
  `SECRET_KEY` is a placeholder (or too short) and `PUBLIC_URL` is an https address.
- **AI helper limits:** the multi-step helper can only call the bot's own tools, always acts on the
  chat it was started for (an id the AI makes up is overwritten), can never read or save API keys, and
  a transfer of ₹5,000 or more waits for your tap on Yes.

## 3. Who can read what

| Who | Amounts, dates, names | Chat history, notes | AI keys |
|---|---|---|---|
| Another Telegram user | No (queries filter by `user_id`; tested). With `ALLOWED_CHAT_IDS` they cannot use the bot at all | No | No |
| Random person on the internet | Not through the API (no endpoint returns data without a Telegram-signed request, as long as a bot token is set and dev endpoints are off) | No | No |
| Someone with a copy of the database file or a backup, **without** `SECRET_KEY` | **Yes** | No | No |
| Someone who reads the DB through a bug such as SQL injection | **Yes** | No (they get ciphertext) | No |
| Someone with the database **and** `.env` / `SECRET_KEY` | Yes | Yes | Yes |
| Someone who controls the running server (or its memory) | Yes | Yes | Yes |
| **You, the operator** (you have the server and `SECRET_KEY`) | **Yes** | **Yes** | **Yes** |
| The AI provider (Gemini, OpenAI, ...) | What the bot sends for a request: recent chat, balances and spending summaries | the recent chat in that request | only the key used for the call |
| Telegram / someone reading the Telegram chat | Anything users typed stays there. API keys sent in chat are redacted in the database and the bot tries to delete the message | same | same |

**What encryption at rest protects against:** a stolen or leaked database file, a lost backup or
disk, a database admin or hosting provider who can read tables but does not have `SECRET_KEY`, and
"read the table" style leaks (SQL injection, a misconfigured DB port).

**What it does not protect against:** a compromised running server (it has the key in memory), the
operator, the AI provider (it receives the prompt in plain text), Telegram, or a weak / leaked
`SECRET_KEY`.

Known software gaps: money is stored as floats (rounded to 2 decimals), there is no rate limiting on the chat itself (the dashboard API is rate limited),
no database migrations, and confirmation state is held in process memory (use one worker).

## 4. How the encryption works

All of it is in [app/crypto.py](../app/crypto.py), about 200 lines.

| What | Key | Format in the database |
|---|---|---|
| `chat_messages.content`, `transactions.description` | HKDF-SHA256(`SECRET_KEY`, label `walletledger/field/v1`) | `enc1:` + Fernet token |
| `api_keys.encrypted_key` | HKDF-SHA256(`SECRET_KEY`, label `walletledger/api-key-vault/v1`) | Fernet token |
| Old API keys saved before this change | `sha256(SECRET_KEY)` (legacy, read-only) | Fernet token |

- **Fernet** = AES-128-CBC with a random IV plus an HMAC-SHA256 tag. Tampered or wrong-key data
  fails to decrypt instead of returning garbage.
- **Separate keys per purpose:** the field key and the vault key are different keys derived from the
  same `SECRET_KEY`, so one cannot be used in place of the other.
- **Automatic:** the two text columns use a SQLAlchemy type (`EncryptedText`) that encrypts on save
  and decrypts on load. The rest of the code just sees plain text.
- **Old rows keep working:** a value without the `enc1:` prefix is treated as old plain text and
  returned as is. Run `scripts/protect_data.py encrypt` once to encrypt them. Old API keys in the
  `sha256(SECRET_KEY)` format still decrypt; `rotate` upgrades them.
- **Wrong key does not crash the bot:** a value no configured key can read is shown as
  `[unreadable: encrypted with a different key]` and a warning is logged once.
- **Search:** "find my transactions about lunch" can no longer be done by the database for notes, so
  the bot loads that user's transactions and matches the decrypted text in Python. Fine for a
  personal ledger (thousands of rows); it would need an index design for millions.

### SECRET_KEY rules

- Use a long random `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  The setup wizard generates one. The built-in default and the `.env.example` placeholder are public:
  `scripts/setup.py --check` flags both, and `protect_data.py` refuses to encrypt with them.
- HKDF is fast, so it does not slow down guessing a weak secret. Random 48+ characters avoids that.
- Keep `SECRET_KEY` somewhere other than the database host's backups, otherwise the encryption adds
  little: whoever gets both gets everything.
- **Losing `SECRET_KEY` means losing the encrypted data** (chat history, notes, stored AI keys).
  Amounts and balances survive. Back up `.env` securely, separately from the database.

### Changing SECRET_KEY (rotation)

1. Back up the database.
2. Put the current value in `SECRET_KEY_OLD` and a new random value in `SECRET_KEY`. Restart.
   The bot writes with the new key and still reads data written with the old one.
3. Run `uv run python scripts/protect_data.py rotate` to re-encrypt everything with the new key.
4. When `status` shows nothing on an old key, remove `SECRET_KEY_OLD`.

`SECRET_KEY_OLD` accepts several values separated by commas.

### The protect_data script

```bash
uv run python scripts/protect_data.py status            # counts per column; changes nothing
uv run python scripts/protect_data.py encrypt --dry-run # how many old plain-text rows
uv run python scripts/protect_data.py encrypt           # asks for confirmation (or --yes)
uv run python scripts/protect_data.py rotate            # after changing SECRET_KEY
```

It works on SQLite and Postgres through the app's own database settings, in batches, and never
prints user text. It is safe to run twice. Deploy the new version of the app **before** running
`encrypt`: an older version would show `enc1:...` instead of the text. The undo is your backup.

## 4b. "Can I read the encrypted data?" (a plain answer)

**Anyone holding the database file but not `SECRET_KEY`: no.** Open `walletledger.db` in a SQLite
viewer and the private text looks like this:

```
transactions.description  ->  enc1:gAAAAABqzF9Fd4mqnKOOgNl0IFa7CIMD9_qA_-F...
chat_messages.content     ->  enc1:gAAAAABqzF7rQz1qGzjPewK2TYt2LNMArQT...
api_keys.encrypted_key    ->  gAAAAABk...
```

Without the key this is random-looking bytes: AES-encrypted, authenticated, and different every time
even for identical text. It cannot be searched or guessed at.

**You, the person running the server, with `SECRET_KEY` in `.env`: yes.** The bot itself decrypts
these values on every request (it must, to answer you), and so can any script that loads the same
`.env`. That is deliberate: "encrypted even from the operator" would mean the bot could not read your
history or notes either. What the encryption buys you is protection for **copies** of the data:
a leaked or stolen `.db` file, a backup in the cloud, a database admin, a SQL-injection dump.
A quick way to see both sides on your own machine (prints only the notes of your own database):

```bash
# 1. what is stored (ciphertext) and 2. what the app can read with SECRET_KEY
uv run python -c "
import sqlite3
from app import crypto
c = sqlite3.connect('file:walletledger.db?mode=ro', uri=True)
for raw, in c.execute('select description from transactions where description is not null limit 3'):
    print(raw[:40], '...  ->  ', crypto.decrypt_text(raw))
"
```

Keep `SECRET_KEY` out of the repo and out of the database backup (store it in a password manager or
the host's secret settings), because **the file and the key together are the data**. If the key is
lost the encrypted columns cannot be recovered; if it changes without `SECRET_KEY_OLD`, they show as
`[unreadable: encrypted with a different key]`.

If you ever need "even the operator cannot read it" (end-to-end), that requires a different design
(keys held only on the user's device) and is listed under "Private mode" below as not implemented.

## 5. How to protect the rest of the data (recommended order)

1. **Disk / volume encryption** (BitLocker, LUKS, encrypted cloud volumes). Cheapest big win; covers
   the plain-text columns, backups and swap.
2. **Postgres in production** (docker-compose is provided) with TLS (`?sslmode=require`), a
   least-privilege user, a private network and encrypted backups. Never expose the DB port.
3. **Secrets:** never commit `.env`, restrict its permissions, prefer your host's secret manager.
4. **HTTPS only** behind a reverse proxy; explicit `TELEGRAM_WEBHOOK_SECRET`; dev endpoints off;
   `ALLOWED_CHAT_IDS` set for a personal bot.
5. **Retention:** limit how long `chat_messages` are kept, add a `/deleteme` command that deletes a
   user (the schema cascades), and avoid logging message bodies.
6. **Monitoring:** alert on repeated 403s at the webhook; keep dependencies updated.

### Private mode (NOT implemented)

The only way to stop the operator from reading data is a key the server does not keep: each user
sets a passphrase, the server derives that user's key from it (with a slow KDF like scrypt), keeps
the key in memory only while the user is "unlocked", and forgets it after a timeout. Trade-offs: the
bot cannot work for a locked user (no reminders, no background imports, no shared reports), a
forgotten passphrase means the data is gone for good, every message would need an unlock step,
amounts and names would still have to be readable to compute totals, and a malicious operator could
still change the code to capture the passphrase the next time the user types it. It also does not
hide anything from the AI provider. That is a product decision, not a quick fix, so it is not built.

## 6. Pre-deploy checklist

- [ ] `SECRET_KEY` random 48+ chars, stored outside the repo, backed up separately from the database
- [ ] `uv run python scripts/protect_data.py status` shows no `plaintext` rows (run `encrypt` once)
- [ ] `TELEGRAM_WEBHOOK_SECRET` set (webhook mode only behind HTTPS)
- [ ] `ENABLE_DEV_ENDPOINTS` unset or `false` while a bot token is configured
- [ ] `ALLOWED_CHAT_IDS` set if the bot is personal/private
- [ ] Postgres with TLS, or SQLite on an encrypted volume
- [ ] `.env` and `*.db` not in git and not world-readable
- [ ] Encrypted backups
- [ ] Users told: delete any message containing an API key
