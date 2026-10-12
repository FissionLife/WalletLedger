"""Run the golden dataset against the real WalletLedger chat router and write a report.

    uv run python -m evals.run_eval --tier rules                  # 0 AI calls
    uv run python -m evals.run_eval --tier rules --mode mcp --repeat 3
    uv run python -m evals.run_eval --tier llm --llm-budget 60    # EVAL_GEMINI_KEYS in .env/shell
    uv run python -m evals.run_eval --tier llm --replay           # re-score saved AI answers

See evals/README.md for the dataset format and the safety rules.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

# ---- environment, BEFORE any app import (never read the real .env, never reach Telegram) -------
_TMP = tempfile.mkdtemp(prefix="walletledger-eval-")
_PROVIDER_VARS = [
    f"{p}_API_KEY{s}"
    for p in ("GEMINI", "OPENAI", "ANTHROPIC", "GROQ", "OPENROUTER", "XAI", "DEEPSEEK", "MISTRAL")
    for s in ("", "S")
]


def _prepare_env(tier: str) -> None:
    os.environ["WALLETLEDGER_TESTING"] = "1"
    os.environ["LITELLM_MODE"] = "PRODUCTION"
    os.environ["DYNAMIC_MODELS"] = "false"
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["TELEGRAM_BOT_TOKENS"] = ""
    os.environ["USE_WEBHOOK"] = "false"
    os.environ["ALLOWED_CHAT_IDS"] = ""
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "eval.db").replace("\\", "/")
    os.environ.pop("OPENAI_BASE_URL", None)  # a corporate gateway in the shell must never be used
    keys = os.environ.get("EVAL_GEMINI_KEYS", "").strip()
    for var in _PROVIDER_VARS:
        os.environ[var] = ""
    if tier in ("llm", "all") and keys:
        os.environ["GEMINI_API_KEYS"] = keys


ROOT = Path(__file__).resolve().parent.parent
KEY_SHAPES = re.compile(r"AIza[0-9A-Za-z_\-]{35}|AQ\.[0-9A-Za-z_.\-]{20,}|sk-[A-Za-z0-9_\-]{20,}")


def scrub(value):
    """Remove anything key-shaped from data before it is written to disk."""
    if isinstance(value, str):
        return KEY_SHAPES.sub("[KEY]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in ("api_key", "api_base")}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tier", choices=("rules", "llm", "all"), default="rules")
    p.add_argument("--mode", choices=("direct", "mcp"), default="direct")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--llm-budget", type=int, default=60, help="max real AI provider requests")
    p.add_argument("--replay", action="store_true", help="serve saved AI answers; 0 requests")
    p.add_argument("--case", action="append", default=[], help="run only these ids")
    p.add_argument("--golden", default=str(ROOT / "evals" / "golden.jsonl"))
    p.add_argument("--out", default=str(ROOT / "evals" / "reports"))
    p.add_argument("--recordings", default=str(ROOT / "evals" / "recordings"))
    return p.parse_args(argv)


def _keys_from_env_file() -> str:
    """EVAL_GEMINI_KEYS from the repo's .env (git-ignored), when not set in the shell.

    Only this one line is read; the rest of .env (bot token, server keys) is never loaded.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == "EVAL_GEMINI_KEYS":
            return value.strip().strip('"').strip("'")
    return ""


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.tier in ("llm", "all") and not args.replay:
        if not os.environ.get("EVAL_GEMINI_KEYS"):
            os.environ["EVAL_GEMINI_KEYS"] = _keys_from_env_file()
        if not os.environ.get("EVAL_GEMINI_KEYS"):
            print("EVAL_GEMINI_KEYS is not set (in the shell or .env). Nothing was run.")
            return 2
    _prepare_env(args.tier)
    os.chdir(_TMP)  # nothing relative (.env, sqlite) can touch the repo
    sys.path.insert(0, str(ROOT))
    from evals import _engine  # noqa: PLC0415  (imports the app; env must be ready first)

    return _engine.run(args, scrub)


if __name__ == "__main__":
    sys.exit(main())
