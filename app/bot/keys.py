"""Chat commands for managing a user's AI keys.

Keys are addressed by their number in /keys, so users never handle internal ids:

    /keys                 list (numbered, masked)
    /setkey <key...>      test live, then save (only working keys are stored)
    /editkey <n> <key>    replace key n with a new one (tested first)
    /delkey <n>           remove key n
    /pausekey <n>         stop using key n without deleting it
    /resumekey <n>        use key n again
    /testkey [n]          re-test one key, or all of them

If a user's keys fail or run out of quota, the team's shared keys (if configured) are used as a
fallback, so the bot keeps working.
"""

from __future__ import annotations

import asyncio
import logging

from app.services_ai import ai_gateway as gw

logger = logging.getLogger(__name__)

KEY_COMMANDS = {
    "/setkey",
    "/key",
    "/keys",
    "/editkey",
    "/delkey",
    "/pausekey",
    "/resumekey",
    "/testkey",
}

SETKEY_USAGE = (
    "🔑 **Add an AI key** (I test it first, and only save it if it works):\n"
    "`/setkey <your key>`\n\n"
    "Supported: Gemini (AIza… or AQ.…), OpenAI (sk-…), Claude (sk-ant-…), Groq (gsk_…).\n"
    "Several keys separated by spaces are fine."
)

_STATUS_ICON = {"valid": "✅", "rate_limited": "⏳", "invalid": "❌", "unverified": "❔"}


def _fallback_line() -> str:
    if gw.has_server_keys():
        return "🛟 If your keys fail or run out, I automatically fall back to the shared team keys."
    return "ℹ️ No shared fallback keys are configured, so if your keys fail I'll switch to offline mode."


def _resolve(chat_id: str, token: str) -> dict | None:
    """Key number (as shown in /keys) -> key record, or None."""
    if not token.isdigit():
        return None
    keys = gw.list_api_keys(chat_id)
    index = int(token) - 1
    return keys[index] if 0 <= index < len(keys) else None


def _bad_number(chat_id: str, usage: str) -> str:
    count = len(gw.list_api_keys(chat_id))
    if count == 0:
        return "🔑 You have no saved keys yet. Add one with `/setkey <key>`."
    return f"❓ Use a key number from /keys (1–{count}). Example: `{usage}`"


# ----------------------------------------------------------------------------------------
# Replies
# ----------------------------------------------------------------------------------------


def keys_text(chat_id: str) -> str:
    keys = gw.list_api_keys(chat_id)
    if not keys:
        return (
            "🔑 You have no AI keys saved yet.\n"
            f"Add one with `/setkey <key>`.\n\n{_fallback_line()}"
        )
    lines = "\n".join(
        f"{n}. {k['provider'].title()}  `{k['masked_key']}`  "
        f"{'✅ active' if k['is_active'] else '⏸️ paused'}"
        for n, k in enumerate(keys, start=1)
    )
    return (
        f"🔑 **Your AI keys:**\n{lines}\n\n"
        "Manage: `/testkey` · `/editkey 1 <new key>` · `/delkey 1` · `/pausekey 1` · `/resumekey 1`\n"
        f"{_fallback_line()}"
    )


async def save_keys(chat_id: str, text: str) -> str:
    """Test every key found in ``text`` live; save the working ones. Used by /setkey and chat."""
    if not text or not text.strip():
        return SETKEY_USAGE
    try:
        results = await gw.add_validated_keys(chat_id, text)
    except Exception:
        logger.exception("Could not save API key(s) for chat %s", chat_id)
        return "⚠️ Something went wrong while saving your key. Please try again."
    if not results:
        return "🔑 I couldn't find a supported API key in that message.\n\n" + SETKEY_USAGE

    lines, saved = [], 0
    for r in results:
        name = r["provider"].title()
        check = r["check"]
        if r["status"] == "rejected":
            if check.status == "invalid":
                lines.append(f"❌ {name} `{r['masked_key']}`: {check.detail}. **Not saved.**")
            else:
                lines.append(
                    f"❔ {name} `{r['masked_key']}`: couldn't verify it right now "
                    f"({check.detail or 'provider unreachable'}). **Not saved** — try again shortly."
                )
            continue
        saved += 1
        if r["status"] == "exists":
            lines.append(f"♻️ {name} `{r['masked_key']}` was already saved (re-activated).")
        elif check.status == "rate_limited":
            lines.append(
                f"⏳ {name} `{r['masked_key']}` is real but {check.detail}. Saved; it'll work again soon."
            )
        else:
            lines.append(f"✅ {name} `{r['masked_key']}` works. Saved (stored encrypted).")

    footer = (
        "\n\n" + _fallback_line()
        if saved
        else (
            "\n\nNothing was saved. Double-check the key (full key, correct provider) and try again."
        )
    )
    return (
        "\n".join(lines)
        + footer
        + "\n\n🧹 I removed your message so the key doesn't stay in the chat."
    )


async def edit_key(chat_id: str, args: str) -> str:
    parts = args.split(None, 1)
    if len(parts) < 2:
        return "✏️ Usage: `/editkey <number> <new key>` (numbers are in /keys)."
    record = _resolve(chat_id, parts[0])
    if record is None:
        return _bad_number(chat_id, "/editkey 1 <new key>")
    found = gw.extract_api_keys(parts[1])
    if not found:
        return "❌ That doesn't look like a supported API key. Nothing was changed."
    provider, new_key = found[0]
    check = await gw.validate_api_key(provider, new_key)
    if not check.usable:
        return (
            f"❌ The new {provider.title()} key didn't pass the test "
            f"({check.detail or 'not verified'}). Your existing key was **not** changed."
        )
    ok = await asyncio.to_thread(gw.replace_api_key, chat_id, record["key_id"], provider, new_key)
    if not ok:
        return "⚠️ Could not update that key. Please try again."
    return (
        f"✅ Key {parts[0]} replaced with {provider.title()} `{gw.mask_key(new_key)}` (tested, stored "
        "encrypted).\n🧹 I removed your message so the key doesn't stay in the chat."
    )


def _simple(chat_id: str, args: str, usage: str, action, done: str) -> str:
    record = _resolve(chat_id, args.strip().split(None, 1)[0] if args.strip() else "")
    if record is None:
        return _bad_number(chat_id, usage)
    if not action(chat_id, record["key_id"]):
        return "⚠️ Could not change that key. Please try again."
    return done.format(n=args.strip().split()[0], name=record["provider"].title())


async def test_keys(chat_id: str, args: str) -> str:
    keys = gw.list_api_keys(chat_id)
    if not keys:
        return "🔑 You have no saved keys to test. Add one with `/setkey <key>`."
    token = args.strip().split()[0] if args.strip() else ""
    if token:
        record = _resolve(chat_id, token)
        if record is None:
            return _bad_number(chat_id, "/testkey 1")
        targets = [(int(token), record)]
    else:
        targets = list(enumerate(keys, start=1))

    async def check(item):
        n, rec = item
        pair = await asyncio.to_thread(gw.get_plain_key, chat_id, rec["key_id"])
        if pair is None:
            return n, rec, gw.KeyCheck("invalid", "can't be decrypted — please re-add it")
        return n, rec, await gw.validate_api_key(*pair)

    lines, any_bad = [], False
    for n, rec, res in await asyncio.gather(*(check(t) for t in targets)):
        any_bad = any_bad or res.status == "invalid"
        detail = f" — {res.detail}" if res.detail else ""
        lines.append(
            f"{_STATUS_ICON[res.status]} {n}. {rec['provider'].title()} `{rec['masked_key']}`: "
            f"{res.status.replace('_', ' ')}{detail}"
        )
    bad = any(r.endswith("") and ("invalid" in ln) for ln in lines for r in [ln])
    hint = (
        "\n\nRemove a bad one with `/delkey <number>` or fix it with `/editkey <number> <new key>`."
        if bad
        else ""
    )
    return "🧪 **Key test results:**\n" + "\n".join(lines) + hint + "\n\n" + _fallback_line()


# ----------------------------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------------------------


async def handle_key_command(chat_id: str, command: str, args: str) -> str | None:
    """Reply for a key command, or None if ``command`` isn't one of ours."""
    if command in ("/setkey", "/key"):
        return await save_keys(chat_id, args)
    if command == "/keys":
        return keys_text(chat_id)
    if command == "/editkey":
        return await edit_key(chat_id, args)
    if command == "/testkey":
        return await test_keys(chat_id, args)
    if command == "/delkey":
        return await asyncio.to_thread(
            _simple, chat_id, args, "/delkey 1", gw.delete_api_key, "🗑️ Key {n} ({name}) removed."
        )
    if command == "/pausekey":
        return await asyncio.to_thread(
            _simple,
            chat_id,
            args,
            "/pausekey 1",
            gw.deactivate_api_key,
            "⏸️ Key {n} ({name}) paused. Use `/resumekey {n}` to turn it back on.",
        )
    if command == "/resumekey":
        return await asyncio.to_thread(
            _simple,
            chat_id,
            args,
            "/resumekey 1",
            gw.activate_api_key,
            "▶️ Key {n} ({name}) is active again.",
        )
    return None
