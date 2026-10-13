# Live demo script (about 8 minutes)

Goal: show that you can talk to your money in Telegram, and that it is safe and easy to run.
Everything below works with no AI key except step 7.

## Before you start (once, 5 minutes)

```bash
uv sync
# (the first start of the server asks for the bot token and your Telegram id)
uv run python scripts/seed_demo_data.py --chat-id <your telegram id> --reset
uv run python scripts/setup_bot.py                    # publishes the "/" menu and bot description
uv run uvicorn main:app --port 8000
```

`--reset` deletes that chat's data first, so use a demo chat (or accept that it replaces your own).
The seed gives you 90 days of believable spending: salary, rent, food apps, travel, subscriptions.
Optional: open a tunnel (`cloudflared tunnel --url http://localhost:8000`), put the address in
`PUBLIC_URL`, restart, and `/dashboard` opens inside Telegram as a Mini App.

Check it is healthy: `uv run python scripts/setup.py --check` (all green) and `/status` in the chat.

## The story

| # | You do | What to point out |
|---|---|---|
| 1 | Send `/start` | Short welcome, tappable menu, no wall of text. Type `/` to show the command list. |
| 2 | *Spent 450 on dinner via Bank* | Two-line reply, balance updates, **↩️ Undo** button. No AI was used: plain rules, instant. |
| 3 | Tap **↩️ Undo**, then send *Spent 200 on chai, 80 on auto, 1500 on petrol yesterday* | Several items in one sentence, "yesterday" becomes a real date. |
| 4 | *is 640 too much for dinner?* | It does **not** log it. Questions are never recorded as spending. |
| 5 | `/stats` then tap the period and chart buttons | Real numbers vs the previous period, charts generated on the fly (13 kinds). |
| 6 | `/dashboard` | Private expiring link; 12 interactive charts, filters, click a bar to drill down, dark mode, works on a phone. |
| 7 | `/setkey <a Gemini key>` then *Can I afford a 50000 laptop in 5 months, and what should I cut?* | Key is tested live before saving, your message with the key is deleted. The AI looks up your real numbers, then answers. |
| 8 | `/plan 60000 6` | Same maths without any AI: needed per month vs what you really keep, and what to trim. |
| 9 | Send a PhonePe / GPay / bank PDF | Preview of what will be imported, with the **statement's own dates**, then Yes. Importing twice adds nothing twice. |
| 10 | `/budget food 6000`, `/export` | Budgets with warnings; your data as CSV any time. |

## If someone asks…

- **Is my data safe?** Chat history, transaction notes and AI keys are encrypted in the database
  (`SECRET_KEY`); keys are tested then stored encrypted; dashboard links are signed and expire; each
  person only ever sees their own Telegram chat id's data. The honest limit: the server can read the
  data (it has to, to answer you). [SECURITY.md](SECURITY.md).
- **Who pays for the AI?** Every user brings their own key (Gemini free tier is enough). The admin can
  optionally provide shared keys as a backup.
- **What if the AI is down or out of quota?** It moves to the next key, then the next provider, then
  carries on with built-in rules. It never just stops.
- **Which AI providers?** Gemini, OpenAI, Claude, Groq, OpenRouter, Grok, DeepSeek, Mistral.
  Model names are discovered automatically; nobody maintains a model list.
- **Can it scale?** Yes: switch `DB_MODE=postgres`, run the included Dockerfile on a serverless host in
  webhook mode. [DEPLOYMENT.md](DEPLOYMENT.md).
- **How does it work inside?** [HOW_IT_WORKS.md](HOW_IT_WORKS.md): one page, no jargon.

## Reset after the demo

```bash
uv run python scripts/seed_demo_data.py --chat-id <your telegram id> --reset
```
