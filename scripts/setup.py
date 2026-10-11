#!/usr/bin/env python3
"""WalletLedger setup wizard: answer a few questions, get a working bot.

    uv run python scripts/setup.py            # guided setup (safe to re-run any time)
    uv run python scripts/setup.py --check    # health check only; changes nothing

It creates .env, makes a strong SECRET_KEY, checks your Telegram bot token, finds your chat id,
picks the database, tests an AI key (optional) and publishes the bot's command menu.
Press Enter at any question to keep the current value / skip.
"""

import argparse
import asyncio
import getpass
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import envfile  # noqa: E402  (safe: does not import the app settings)

ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def say(msg: str = "") -> None:
    print(msg)


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else (" [keep current]" if default else "")
    raw = (getpass.getpass if secret else input)(f"{prompt}{suffix}: ").strip()
    return raw or default


def yes(prompt: str, default: bool = True) -> bool:
    raw = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not raw else raw.startswith("y")


async def check_token(token: str):
    from aiogram import Bot

    bot = Bot(token=token)
    try:
        return await bot.get_me()
    finally:
        await bot.session.close()


async def detect_chat_id(token: str, seconds: int = 60) -> str | None:
    """Wait for the user to message the bot and return that chat id. Only reads updates."""
    from aiogram import Bot

    bot = Bot(token=token)
    try:
        for _ in range(seconds // 3):
            updates = await bot.get_updates(timeout=2, allowed_updates=["message"])
            for u in reversed(updates):
                if u.message and u.message.chat.type == "private":
                    return str(u.message.chat.id)
            await asyncio.sleep(1)
    finally:
        await bot.session.close()
    return None


def step_env_file() -> None:
    if not ENV.exists():
        shutil.copyfile(EXAMPLE, ENV)
        say("Created .env from .env.example")


def step_secret() -> None:
    from app.config import INSECURE_DEV_KEY

    current = envfile.read_env(ENV).get("SECRET_KEY", "")
    if current and current != INSECURE_DEV_KEY and current != "change-me-to-a-long-random-string":
        say("SECRET_KEY: already set (kept).")
        return
    envfile.set_values(ENV, {"SECRET_KEY": secrets.token_urlsafe(48)})
    say("SECRET_KEY: generated a strong random one.")


def step_telegram() -> str:
    values = envfile.read_env(ENV)
    say("\nTelegram bot")
    say("  Create one in Telegram: open @BotFather, send /newbot, copy the token it gives you.")
    while True:
        token = ask("  Bot token", values.get("TELEGRAM_BOT_TOKEN", ""), secret=True)
        if not token:
            say("  Skipped: the bot stays off until you set TELEGRAM_BOT_TOKEN.")
            return ""
        try:
            me = asyncio.run(check_token(token))
        except Exception as exc:
            say(f"  That token didn't work ({type(exc).__name__}). Check it and try again.")
            if not yes("  Try again?"):
                return ""
            continue
        say(f"  OK: @{me.username}")
        envfile.set_values(ENV, {"TELEGRAM_BOT_TOKEN": token})
        return token


def step_owner(token: str) -> None:
    values = envfile.read_env(ENV)
    say("\nWho may use the bot (and manage shared AI keys)?")
    current = values.get("ADMIN_CHAT_IDS", "") or values.get("ALLOWED_CHAT_IDS", "")
    chat_id = current
    if (
        token
        and not current
        and yes("  Detect your Telegram id now? (send any message to your bot)")
    ):
        say("  Waiting up to 60 seconds... open your bot in Telegram and send it any message.")
        found = asyncio.run(detect_chat_id(token))
        if found:
            say(f"  Found your id: {found}")
            chat_id = found
        else:
            say("  Nothing received. You can type it in manually (ask @userinfobot for your id).")
    chat_id = ask("  Your Telegram id", chat_id)
    if chat_id:
        envfile.set_values(ENV, {"ADMIN_CHAT_IDS": chat_id, "ALLOWED_CHAT_IDS": chat_id})
        say("  Saved: only you can use the bot, and you are the admin.")
        say("  (To add friends later, put their ids in ALLOWED_CHAT_IDS, separated by commas.)")
    else:
        say("  Skipped: anyone who finds the bot can use it. Fix this before sharing the bot.")


def step_database() -> None:
    say("\nDatabase")
    say("  sqlite = a single file, no setup (recommended to start). postgres = a database server.")
    mode = ask(
        "  Choose sqlite or postgres", envfile.read_env(ENV).get("DB_MODE", "sqlite")
    ).lower()
    if mode not in ("sqlite", "postgres"):
        mode = "sqlite"
    envfile.set_values(ENV, {"DB_MODE": mode})
    if mode == "postgres":
        say("  Start it with:  docker compose up -d   (settings are in .env: POSTGRES_*)")


def step_ai_key() -> None:
    say("\nAI key (optional, unlocks free-form chat and advice)")
    say("  Without one the bot still works with built-in rules. Gemini keys start with AIza or AQ.")
    key = ask("  Paste a key to test and save as the shared key (Enter to skip)", secret=True)
    if not key:
        return
    # Import the app only now, after .env is final, so it reads the right settings.
    from app.db import init_db
    from app.services_ai import ai_gateway as gw

    found = gw.extract_api_keys(key)
    if not found:
        say("  That doesn't look like a Gemini/OpenAI/Claude/Groq key. Skipped.")
        return
    provider, clean = found[0]
    say(f"  Testing your {gw.label(provider)} key...")
    check = asyncio.run(gw.validate_api_key(provider, clean))
    if not check.usable:
        say(f"  Not saved: {check.detail or check.status}")
        return
    init_db()
    result = gw.add_api_key(gw.SHARED_OWNER, provider, clean)
    say(
        f"  Saved ({result['status']}): {gw.label(provider)} {result['masked_key']} (stored encrypted)"
    )


def step_profile() -> None:
    from app.config import settings

    if not settings.telegram_bot_token.strip():
        return
    say("\nPublishing the bot's command menu...")
    from aiogram import Bot

    from app.bot import profile

    async def go():
        bot = Bot(token=settings.telegram_bot_token)
        try:
            return await profile.apply_profile(bot)
        finally:
            await bot.session.close()

    results = asyncio.run(go())
    bad = {k: v for k, v in results.items() if v != "ok"}
    say("  Done." if not bad else f"  Partly done: {bad}")


def doctor() -> int:
    """Health check: everything a first-time user can get wrong, in plain words."""
    from app import health
    from app.config import settings
    from app.db import describe_database

    say("WalletLedger health check\n")
    problems = health.setup_problems()
    ok = True
    if settings.telegram_bot_token.strip():
        try:
            me = asyncio.run(check_token(settings.telegram_bot_token))
            say(f"OK    Telegram token works (@{me.username})")
        except Exception as exc:
            ok = False
            say(f"FAIL  Telegram token rejected ({type(exc).__name__})")
    for p in problems:
        ok = False
        say(f"WARN  {p}")
    say(f"OK    Storage: {describe_database()}")
    try:
        path = asyncio.run(health.ai_path("__doctor__"))
    except Exception:  # fresh database: tables are created the first time the server starts
        path = health.AIPath(0, 0, 0, None, None)
        say("INFO  Database not initialised yet (it is created the first time the server starts)")
    if path.has_ai:
        say(f"OK    AI available ({path.mode}); model {path.first_model}")
    else:
        say(
            "INFO  No AI key yet: basic commands work, free-form chat is off. Add one with the wizard"
        )
        say("      or send /admin addkey <key> to your bot.")
    say("\nAll good." if ok else "\nFix the items above, then run this check again.")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--check", action="store_true", help="health check only, changes nothing")
    args = ap.parse_args()
    if args.check:
        return doctor()

    say("WalletLedger setup. Press Enter to keep a value or skip a step.\n")
    step_env_file()
    step_secret()
    token = step_telegram()
    step_owner(token)
    step_database()
    step_ai_key()
    step_profile()
    say("\nAll set. Start the bot with:")
    say("    uv run uvicorn main:app --port 8000")
    say("Then open your bot in Telegram and send /start. Check health any time with:")
    say("    uv run python scripts/setup.py --check")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
