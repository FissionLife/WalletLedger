# Running WalletLedger with Cloudflare

Short answer: **you can't run the app itself on plain Cloudflare Workers, but you can run it with Cloudflare
in three ways.** Pick by how much you want to set up.

| Option | What you get | Effort | Status |
|---|---|---|---|
| **A. Cloudflare Tunnel** | The dashboard and Telegram Mini App work from your own computer or any server. Free. | one command | works today |
| **B. Cloudflare Containers** | The same Docker image runs on Cloudflare's network, sleeps when idle, wakes on a message. | an afternoon, needs a paid Workers plan and a hosted Postgres | scaffolding included, **not yet tested on a live account** |
| **C. Pure Workers** (Python or JavaScript) | Fully serverless, no container. | a rewrite | **not possible with this code**, see below |

## Why not plain Workers?

A Worker is a short-lived function that runs in a sandbox. WalletLedger is a long-lived Python program:

- **The packages don't fit.** Python Workers exist (generally available in 2026) but only run pure-Python
  packages and ones Cloudflare has compiled to WebAssembly. WalletLedger's stack (LiteLLM, LangGraph,
  aiogram, SQLAlchemy with SQLite or `psycopg2`, matplotlib for the Telegram charts) is a long way from
  that list, and some of it needs threads, which the WebAssembly runtime doesn't have.
- **No local disk.** The default database is a SQLite file. A Worker has no disk that survives.
- **Polling needs a process that stays alive.** (Webhook mode, where Telegram calls you, does suit Workers.)

A fully serverless version would be a rewrite in TypeScript using **D1** (Cloudflare's SQLite) for data and
the Telegram webhook, with charts drawn as SVG in the browser instead of PNGs. That is possible, but it
would be a second codebase to maintain, so it is deliberately not part of this project.

## Option A: Cloudflare Tunnel (recommended to start)

A tunnel gives your computer a public `https` address without opening any port. The bot still runs where
it runs now; the tunnel only lets Telegram open your **dashboard** as a Mini App.

1. Install the `cloudflared` program once:
   - Windows: `winget install Cloudflare.cloudflared`
   - macOS: `brew install cloudflared`
   - Linux: see the [download page](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. Start everything with one command:

   ```bash
   uv run python scripts/tunnel.py
   ```

   It starts the tunnel, waits for the address (like `https://something.trycloudflare.com`), starts the
   server with `PUBLIC_URL` set to it, and prints it. Send `/dashboard` in Telegram: it opens inside the app.
   `Ctrl+C` stops both.

The server refuses to start behind a public address with the placeholder `SECRET_KEY`, so run the
setup wizard (`uv run python scripts/setup.py`) first; it generates a strong one.

Good to know about **quick tunnels**: free, no account, but the address is **new every run** (old dashboard
links stop working) and Cloudflare describes them as for testing (about 200 simultaneous requests).
Perfect for a demo. Add `--webhook` to let Telegram push messages through the tunnel instead of polling.

### Your own tunnel (stable address)

You need a domain on Cloudflare. In the Cloudflare dashboard open **Zero Trust → Networks → Tunnels →
Create a tunnel → Cloudflared**, copy the token, and add a **Public hostname** such as
`wallet.yourdomain.com` pointing at `http://localhost:8000`. Then in `.env`:

```
CLOUDFLARE_TUNNEL_TOKEN=<the token>
PUBLIC_URL=https://wallet.yourdomain.com
```

and run `uv run python scripts/tunnel.py --named`.

**With Docker** (app, Postgres and tunnel together):

```bash
docker compose --profile app --profile tunnel up -d --build
```

In the tunnel's Public hostname settings use the service `http://app:8080` instead of `localhost`.

## Option B: Cloudflare Containers

[Containers](https://developers.cloudflare.com/containers/) (generally available since April 2026) run an
ordinary Docker image, controlled by a small Worker. WalletLedger already has a `Dockerfile`, so the
files in `cloudflare/` are a thin wrapper:

```
Telegram / browser  ->  Worker (cloudflare/src/index.js)  ->  container (the Dockerfile)  ->  your Postgres
```

How it behaves:

- The container **sleeps after 20 idle minutes** and **wakes on the next request** (cold start of a few
  seconds; Telegram retries a webhook that arrives too early).
- Its **disk is erased on every sleep**, so the database must be an outside **Postgres** (Neon, Supabase,
  Cloud SQL, ...). That is already `DB_MODE=postgres`; the wrapper sets it for you.
- It runs in **webhook mode** (Telegram pushes messages), because polling can't work while asleep.
- Needs the **Workers Paid plan** (about $5 a month when written; Containers usage is billed on top of an
  included allowance; check current [pricing](https://developers.cloudflare.com/containers/pricing/)).

Deploy:

```bash
cd cloudflare
npm install
# 1. Put your Worker's address in wrangler.jsonc ("PUBLIC_URL"), e.g. https://walletledger.<you>.workers.dev
# 2. Store secrets (each command asks for the value; nothing goes in a file):
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put SECRET_KEY            # the same value every time; see docs/SECURITY.md
npx wrangler secret put DATABASE_URL          # postgresql://user:pass@host:5432/db?sslmode=require
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
# optional: ALLOWED_CHAT_IDS, ADMIN_CHAT_IDS, GEMINI_API_KEYS, ...
# 3. Deploy (Docker must be running; the first deploy builds the image and takes a while)
npx wrangler deploy
# 4. Wake it once so it registers the Telegram webhook:
curl https://walletledger.<you>.workers.dev/health
```

Secrets are only read when the container starts, so after changing one, redeploy or wait for it to sleep.

**Honest status:** this wrapper follows Cloudflare's documented Containers setup but has not been run
against a live Cloudflare account by the authors. Expect to adjust `wrangler.jsonc` (instance size,
region) to your account, and check the current Containers docs if a command has changed.

## Which should I use?

- Showing it to someone, or running it on your own machine: **A**. One command.
- A small always-available bot with no server to look after: **B**.
- Any ordinary VPS or PaaS: skip Cloudflare hosting and use the [Dockerfile](DEPLOYMENT.md); optionally add
  a named tunnel from **A** for the https address.
