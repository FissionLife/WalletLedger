#!/usr/bin/env python3
"""Build the project map: a machine-readable index and a self-contained explorer page.

    uv run python scripts/build_map.py            # rewrite docs/project-map.json and site/explore/index.html
    uv run python scripts/build_map.py --check    # exit 1 if a file has no plain-language note

What it does: reads every Python file with the standard `ast` module (no imports, no network, no AI),
and records each file's layer, a plain-language note, its classes/functions with line numbers, and
which other project files it imports. The notes below are written by hand; everything else comes
from the code, so the map cannot drift from the real files.

Outputs (both committed, so nobody has to rebuild them to look around):
    docs/PROJECT_MAP.md        a compact text index (~20 KB): read this first, instead of the code
    docs/project-map.json      the same facts as data, for tools
    site/explore/index.html    the interactive explorer (published with the landing page)

When you add a file, add a line to NOTES. `--check` (and tests/test_project_map.py) tell you if you forgot.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/FissionLife/WalletLedger"
JSON_OUT = ROOT / "docs" / "project-map.json"
MD_OUT = ROOT / "docs" / "PROJECT_MAP.md"
HTML_OUT = ROOT / "site" / "explore" / "index.html"
TEMPLATE = Path(__file__).with_name("map_template.html")
APP_JS = Path(__file__).with_name("map_app.js")

# ------------------------------------------------------------------------------ the layers
# (id, title, one line). Order = left to right in the explorer.
LAYERS = [
    ("entry", "Start", "Where the program begins and how it is configured"),
    ("chat", "Chat", "Everything the user sees in Telegram"),
    ("brain", "Brain", "Understands the message and decides what to do"),
    ("money", "Money", "The numbers: ledger, analytics, charts"),
    ("ai", "AI", "Talking to AI providers, tools the AI may call"),
    ("web", "Web", "The dashboard and Telegram Mini App"),
    ("data", "Data & safety", "Database, encryption, health"),
    ("ops", "Scripts", "Setup, demo data, maintenance"),
    ("tests", "Tests", "Offline checks that protect everything above"),
    ("site", "Site & deploy", "Landing page, container, CI"),
]

# path -> (layer, plain-language note)
NOTES: dict[str, tuple[str, str]] = {
    "main.py": (
        "entry",
        "Starts everything: database, Telegram bot, the web routes. `app/main.py` just re-exports it.",
    ),
    "app/config.py": (
        "entry",
        "Every setting, read from `.env`. Also answers 'is this chat allowed?' and 'is this chat an admin?'.",
    ),
    "app/bot/telegram.py": (
        "chat",
        "The Telegram connection: receives messages, buttons and files, sends replies (text, charts, CSV), publishes the bot profile. Polling or webhook.",
    ),
    "app/bot/main.py": (
        "chat",
        "The command list (`COMMAND_MENU`), help text, and the router that decides what each message is. Also the PDF import flow.",
    ),
    "app/bot/views.py": (
        "chat",
        "The screens: stats, charts, balance, history, budgets, savings plan, undo, export, dashboard link.",
    ),
    "app/bot/ui.py": (
        "chat",
        "What a reply looks like (text + image + buttons) and the button data format. No Telegram types, so tests can use it.",
    ),
    "app/bot/callbacks.py": ("chat", "What happens when someone taps a button."),
    "app/bot/replies.py": (
        "chat",
        "The short wording of replies: two-line confirmations, friendly errors, hints.",
    ),
    "app/bot/fmt.py": (
        "chat",
        "Formatting helpers: ₹1,25,000 style numbers, dates, bars, plurals.",
    ),
    "app/bot/keys.py": (
        "chat",
        "`/setkey /keys /testkey /editkey /delkey /pausekey /resumekey /admin`: managing AI keys from the chat.",
    ),
    "app/bot/profile.py": (
        "chat",
        "The bot's Telegram profile: command menu, description, menu button. Used by `scripts/setup_bot.py`.",
    ),
    "app/bot/nlu.py": (
        "brain",
        "Plain-message reader built from rules, no AI: amounts, dates, accounts, categories, several items per message, questions, savings goals.",
    ),
    "app/bot/agent.py": (
        "brain",
        "The LangGraph agent: remembers pending confirmations, picks tools, writes replies, falls back to rules when the AI fails.",
    ),
    "app/bot/orchestrator.py": (
        "brain",
        "The multi-step loop for goals and questions: AI picks tools, we run them, AI answers. Capped steps, safe tool list.",
    ),
    "app/services/ledger.py": (
        "money",
        "The ONLY code that changes balances: record expense/income, transfer, undo, history. Validates every amount.",
    ),
    "app/services/analytics.py": (
        "money",
        "All the numbers: periods and filters, breakdowns, trends, budgets, projections, savings plan, insights.",
    ),
    "app/charts.py": ("money", "Draws the 13 chart pictures (PNG) and the overview image."),
    "app/services_ai/ai_gateway.py": (
        "ai",
        "Which AI key and model to use: key order, rotation, fallback, live key testing, provider detection.",
    ),
    "app/services_ai/model_catalog.py": (
        "ai",
        "Asks each provider which models a key can use and picks the best, so model names are never hard-coded.",
    ),
    "app/services_ai/mcp_server.py": (
        "ai",
        "The tool registry: the functions the AI may call (log expense, transfer, savings plan ...).",
    ),
    "app/services_ai/tool_client.py": (
        "ai",
        "One door for every tool call: plain Python (`TOOL_MODE=direct`, default) or the real MCP server over stdio (`TOOL_MODE=mcp`, demo mode). The agent, helper and PDF import only call this.",
    ),
    "app/services_ai/mcp_transport.py": (
        "ai",
        "Serves the same tools over MCP so other agents can use them.",
    ),
    "app/services_ai/prompts.py": ("ai", "The three advice personas: Coach, Budgeter, Summary."),
    "app/services_ai/transaction_parser.py": (
        "ai",
        "Reads statements: PhonePe, GPay, Paytm, BHIM, bank tables, SMS. Guesses categories.",
    ),
    "app/web/tokens.py": (
        "web",
        "Signed, expiring dashboard links and the Telegram Mini App sign-in check.",
    ),
    "app/web/dashboard.py": ("web", "The dashboard's web API and security headers."),
    "app/web/static/dashboard.html": ("web", "The dashboard page."),
    "app/web/static/dashboard.css": ("web", "Dashboard styling (light and dark, phone friendly)."),
    "app/web/static/dashboard.js": (
        "web",
        "Draws the 12 SVG charts, filters, drill-down and the transactions table. No libraries.",
    ),
    "app/db.py": ("data", "Database connection for SQLite or Postgres."),
    "app/models.py": ("data", "The 8 tables. Marks which columns are encrypted."),
    "app/crypto.py": (
        "data",
        "Encryption: HKDF-derived keys, Fernet, `enc1:` format, key rotation, the encrypted column type.",
    ),
    "app/health.py": ("data", "Plain-language health report: `/status` and the setup check."),
    "app/envfile.py": (
        "data",
        "Safe `.env` editor used by the setup wizard (keeps comments, makes a backup).",
    ),
    "sql/schema.sql": ("data", "The schema as SQL (generated)."),
    "scripts/setup.py": ("ops", "Setup wizard and `--check` health check."),
    "scripts/setup_bot.py": (
        "ops",
        "Publishes the command menu and description to Telegram; `--show` compares with the code.",
    ),
    "scripts/protect_data.py": (
        "ops",
        "Encrypts older rows, shows progress, rotates `SECRET_KEY`.",
    ),
    "scripts/seed_demo_data.py": ("ops", "90 days of believable demo data for a chat."),
    "scripts/inspect_statement.py": ("ops", "Shows how a statement PDF is read, line by line."),
    "scripts/generate_schema.py": ("ops", "Regenerates `sql/schema.sql` from the models."),
    "scripts/build_docs.py": (
        "ops",
        "Turns the Markdown docs into pages of the website (shared header, diagrams); CI runs it, nothing is committed.",
    ),
    "scripts/docs_template.html": ("ops", "The layout of the docs pages on the website."),
    "tests/test_build_docs.py": (
        "tests",
        "Docs become website pages: links, diagrams, shared header.",
    ),
    "scripts/tunnel.py": (
        "ops",
        "One command: starts a Cloudflare Tunnel and the server, so /dashboard opens inside Telegram.",
    ),
    "cloudflare/src/index.js": (
        "site",
        "Optional Cloudflare Containers wrapper: a tiny Worker that wakes the Docker image and forwards requests.",
    ),
    "cloudflare/wrangler.jsonc": (
        "site",
        "Config for the Cloudflare Containers wrapper (image, instance size, public address).",
    ),
    "cloudflare/package.json": (
        "site",
        "Dependencies for the Cloudflare wrapper (wrangler and the containers helper).",
    ),
    "docker-compose.yml": (
        "site",
        "Postgres, plus optional profiles for the app container and a Cloudflare Tunnel.",
    ),
    "tests/test_tunnel.py": (
        "tests",
        "Tunnel runner helpers and the Cloudflare/compose files (nothing is started).",
    ),
    "scripts/build_map.py": (
        "ops",
        "Builds this map and the explorer page. Runs by itself on every push (see the Pages workflow).",
    ),
    "scripts/map_template.html": (
        "ops",
        "The explorer page's layout and styling (a template for build_map.py).",
    ),
    "scripts/map_app.js": (
        "ops",
        "The explorer page's behaviour: tours, map, search, detail panel.",
    ),
    "CLAUDE.md": (
        "entry",
        "Orientation for AI coding assistants: read the map first, the rules of the codebase, how to run things.",
    ),
    "tests/__init__.py": (
        "tests",
        "Runs before every test: makes sure tests never reach the real Telegram or read your `.env`.",
    ),
    "tests/test_multi_bot.py": (
        "tests",
        "Several Telegram bots on one backend: tokens, webhook addresses and secrets, start/stop, shared ledger.",
    ),
    "tests/test_audit_fixes.py": (
        "tests",
        "Regression tests for the bugs found in the code audit: lost balance updates, junk entries, undo order, dashboard.",
    ),
    "tests/test_agent.py": ("tests", "The agent: confirmations, tool use, fallbacks."),
    "tests/test_ai_gateway.py": ("tests", "Key order, rotation, live key tests."),
    "tests/test_analytics.py": ("tests", "Periods, filters, breakdowns, projections, charts."),
    "tests/test_bot.py": ("tests", "Commands, imports, replies end to end."),
    "tests/test_bot_profile.py": ("tests", "The Telegram menu stays in sync with the code."),
    "tests/test_bot_ui.py": ("tests", "Buttons, callbacks, screens."),
    "tests/test_dashboard_web.py": ("tests", "Dashboard links, sign-in, API, security headers."),
    "tests/test_database_modes.py": ("tests", "SQLite and Postgres settings."),
    "tests/test_encryption.py": ("tests", "Encrypted columns, rotation, legacy data."),
    "tests/test_envfile_and_setup.py": ("tests", "The setup wizard and `.env` editor."),
    "tests/test_key_management.py": ("tests", "/setkey and friends."),
    "tests/test_ledger_and_access.py": (
        "tests",
        "Balances, validation, undo, who may use the bot.",
    ),
    "tests/test_mcp_tools.py": ("tests", "The AI tools."),
    "tests/test_model_catalog.py": ("tests", "Model discovery and ranking."),
    "tests/test_model_fallback.py": ("tests", "Trying the next model or key when one fails."),
    "tests/test_nlu.py": ("tests", "The message-reading rules."),
    "tests/test_planning.py": ("tests", "Savings plans, /plan, questions, the multi-step helper."),
    "tests/test_project_map.py": ("tests", "Every file has a note in this map."),
    "tests/test_providers.py": (
        "tests",
        "The eight AI providers and bring-your-own-key onboarding.",
    ),
    "tests/test_shared_keys_admin.py": ("tests", "Shared keys and /admin."),
    "tests/test_statement_formats.py": (
        "tests",
        "Every statement format, with synthetic examples.",
    ),
    "tests/test_tool_mode.py": (
        "tests",
        "TOOL_MODE direct vs mcp: starts the real MCP server process against a throwaway database.",
    ),
    "tests/test_transaction_parser.py": ("tests", "Statement parsing basics."),
    "tests/test_evals.py": (
        "tests",
        "The agent evaluation: scoring rules, the golden file's shape, a small rules-tier run.",
    ),
    "site/index.html": ("site", "The landing page."),
    "site/styles.css": ("site", "Landing page styling and the colour tokens."),
    "site/app.js": ("site", "Small landing page behaviours (theme, copy buttons)."),
    "Dockerfile": ("site", "Runs the app in a container on any host."),
    ".github/workflows/lint.yml": ("site", "CI: runs the tests and ruff on every push."),
    ".github/workflows/pages.yml": ("site", "Publishes `site/` to GitHub Pages."),
}

# Files without a Python AST (listed from NOTES; symbols stay empty)
NON_PYTHON = {p for p in NOTES if not p.endswith(".py")}

TOURS = [
    {
        "title": "A message becomes a transaction",
        "ask": "You send: Spent 200 on chai, 80 on auto yesterday",
        "steps": [
            ("app/bot/telegram.py", "Telegram delivers the message to the bot."),
            (
                "app/bot/main.py",
                "`handle_incoming` checks you are allowed, and that it is not a /command or a screen.",
            ),
            ("app/bot/agent.py", "The agent runs. First it asks the rules to read the message."),
            (
                "app/bot/nlu.py",
                "Rules find 2 items, the amounts, the category words and the date. No AI is used.",
            ),
            (
                "app/services_ai/tool_client.py",
                "Each item becomes a tool call (`log_expense`), sent through the one tool door: plain Python, or the MCP server in demo mode.",
            ),
            (
                "app/services_ai/mcp_server.py",
                "The tool itself: validates the arguments and calls the ledger.",
            ),
            (
                "app/services/ledger.py",
                "The ledger validates and saves the transaction and updates the balance together.",
            ),
            ("app/bot/replies.py", "A two-line reply is written, and an Undo button is attached."),
        ],
    },
    {
        "title": "A question for the AI",
        "ask": "You send: Can I afford a 50000 laptop in 5 months?",
        "steps": [
            ("app/bot/main.py", "Not a command, not a screen: it goes to the agent."),
            ("app/bot/nlu.py", "Rules see a question, so nothing is logged."),
            ("app/bot/orchestrator.py", "The multi-step helper starts (needs an AI key)."),
            (
                "app/services_ai/ai_gateway.py",
                "Picks your key (then shared, then server keys) and the best model.",
            ),
            (
                "app/services_ai/mcp_server.py",
                "The AI calls `savings_plan` / `get_financial_snapshot`.",
            ),
            ("app/services/analytics.py", "Real numbers from your last 90 days come back."),
            ("app/bot/orchestrator.py", "The AI reads them and writes a short answer."),
        ],
    },
    {
        "title": "/dashboard",
        "ask": "You send: /dashboard",
        "steps": [
            ("app/bot/views.py", "Builds a private link, valid for 2 hours."),
            ("app/web/tokens.py", "Signs the link (chat id + expiry) so it cannot be forged."),
            ("app/web/dashboard.py", "Checks the signature, serves the page and the data."),
            ("app/services/analytics.py", "Computes the same numbers the Telegram charts use."),
            ("app/web/static/dashboard.js", "The browser draws 12 charts from that data."),
        ],
    },
    {
        "title": "Importing a PhonePe PDF",
        "ask": "You send a statement PDF",
        "steps": [
            ("app/bot/telegram.py", "Downloads the file (size and type checked)."),
            ("app/bot/main.py", "Starts the import flow and shows a preview."),
            (
                "app/services_ai/transaction_parser.py",
                "Detects the format, reads rows with the statement's own dates, guesses categories.",
            ),
            ("app/bot/main.py", "You tap Import: rows already in the ledger are skipped."),
            ("app/services/ledger.py", "Each new row is saved with its real date."),
        ],
    },
    {
        "title": "Adding an AI key, safely",
        "ask": "You send: /setkey AIza...",
        "steps": [
            ("app/bot/keys.py", "Finds the provider from the key's shape."),
            (
                "app/services_ai/ai_gateway.py",
                "Tests the key live with a real model. Only a working key is saved.",
            ),
            ("app/crypto.py", "The key is encrypted with its own derived key."),
            ("app/models.py", "Stored in `api_keys.encrypted_key`."),
            ("app/bot/telegram.py", "Your message is deleted from the chat."),
        ],
    },
]

# command -> file that handles it (the description comes from COMMAND_MENU in the code)
COMMAND_HOME = {
    "start": "app/bot/main.py", "menu": "app/bot/views.py", "balance": "app/bot/views.py",
    "stats": "app/bot/views.py", "history": "app/bot/views.py", "undo": "app/bot/views.py",
    "budget": "app/bot/views.py", "plan": "app/bot/views.py", "dashboard": "app/bot/views.py",
    "export": "app/bot/views.py", "coach": "app/bot/agent.py", "budgeter": "app/bot/agent.py",
    "summary": "app/bot/agent.py", "keys": "app/bot/keys.py", "setkey": "app/bot/keys.py",
    "status": "app/health.py", "help": "app/bot/main.py", "chart": "app/bot/views.py",
    "report": "app/bot/views.py", "admin": "app/bot/keys.py", "testkey": "app/bot/keys.py",
    "editkey": "app/bot/keys.py", "delkey": "app/bot/keys.py", "pausekey": "app/bot/keys.py",
    "resumekey": "app/bot/keys.py", "key": "app/bot/keys.py",
}  # fmt: skip

TABLES = [
    ("users", "One row per Telegram chat id. This is the identity everything hangs on.", []),
    ("accounts", "Your pipes: Cash, Bank, cards. Holds the balance.", []),
    ("categories", "Spending/income categories and monthly budgets.", []),
    ("merchants", "Who you paid, with a default category.", []),
    ("transactions", "Every expense, income and transfer.", ["description"]),
    ("subscriptions", "Recurring bills.", []),
    ("chat_messages", "What you and the bot said.", ["content"]),
    ("api_keys", "AI keys users added (and shared keys under `__shared__`).", ["encrypted_key"]),
]


# ------------------------------------------------------------------------------ reading code


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().splitlines()[0].strip() if doc and doc.strip() else ""


def _module_name(rel: str) -> str:
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


def read_python(rel: str, known_modules: dict[str, str]) -> tuple[list[dict], list[str], int]:
    """(symbols, internal files imported, line count) for one Python file."""
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    symbols: list[dict] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            if node.name.startswith("_") and kind == "function":
                continue  # private helpers stay out of the map
            symbols.append(
                {
                    "name": node.name,
                    "kind": kind,
                    "line": node.lineno,
                    "doc": _first_line(ast.get_docstring(node)),
                }
            )
    imports: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names += [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        for name in names:
            if name in known_modules and known_modules[name] != rel:
                imports.add(known_modules[name])
    return symbols, sorted(imports), len(text.splitlines())


def python_files() -> list[str]:
    out = ["main.py"]
    for folder in ("app", "scripts", "tests"):
        for p in sorted((ROOT / folder).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if p.name == "__init__.py" and not any(
                not isinstance(n, ast.Expr) for n in ast.parse(p.read_text(encoding="utf-8")).body
            ):
                continue  # an empty package marker is not worth a box on the map
            if "__pycache__" in rel or rel == "app/main.py":
                continue
            out.append(rel)
    return out


def commands() -> list[dict]:
    """COMMAND_MENU and HIDDEN_COMMANDS read straight from app/bot/main.py (no import)."""
    tree = ast.parse((ROOT / "app/bot/main.py").read_text(encoding="utf-8"))
    menu: list[tuple[str, str]] = []
    hidden: list[str] = []
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == "COMMAND_MENU" and value is not None:
            menu = list(ast.literal_eval(value))
        if target == "HIDDEN_COMMANDS" and value is not None:
            hidden = list(ast.literal_eval(value))
    rows = [
        {
            "command": f"/{c}",
            "what": d,
            "file": COMMAND_HOME.get(c, "app/bot/main.py"),
            "menu": True,
        }
        for c, d in menu
    ]
    rows += [
        {
            "command": f"/{c}",
            "what": "Works, but not in the menu.",
            "file": COMMAND_HOME.get(c, "app/bot/main.py"),
            "menu": False,
        }
        for c in hidden
    ]
    return rows


def build() -> tuple[dict, list[str]]:
    files = python_files()
    missing = [f for f in files if f not in NOTES]
    missing += [f for f in NOTES if not (ROOT / f).exists()]
    known = {_module_name(f): f for f in files}
    nodes = []
    for rel, (layer, note) in NOTES.items():
        if not (ROOT / rel).exists():
            continue
        if rel in NON_PYTHON:
            symbols, imports, lines = (
                [],
                [],
                len((ROOT / rel).read_text(encoding="utf-8").splitlines()),
            )
        else:
            symbols, imports, lines = read_python(rel, known)
        nodes.append(
            {
                "path": rel,
                "layer": layer,
                "note": note,
                "lines": lines,
                "symbols": symbols,
                "uses": imports,
            }
        )
    by_path = {n["path"]: n for n in nodes}
    for n in nodes:
        n["used_by"] = sorted(m["path"] for m in nodes if n["path"] in m["uses"])
    data = {
        "name": "WalletLedger",
        "repo": REPO,
        "layers": [{"id": i, "title": t, "about": a} for i, t, a in LAYERS],
        "files": nodes,
        "tours": [
            {
                "title": t["title"],
                "ask": t["ask"],
                "steps": [{"path": p, "text": x} for p, x in t["steps"] if p in by_path],
            }
            for t in TOURS
        ],
        "commands": commands(),
        "tables": [{"name": n, "about": a, "encrypted": e} for n, a, e in TABLES],
        "totals": {
            "files": len(nodes),
            "app_lines": sum(
                n["lines"] for n in nodes if n["layer"] not in ("tests", "site", "ops")
            ),
            "test_lines": sum(n["lines"] for n in nodes if n["layer"] == "tests"),
        },
    }
    return data, sorted(set(missing))


def markdown(data: dict) -> str:
    """A compact text index (about 20 KB): small enough for a person or an AI to read in one go."""
    out = [
        "# WalletLedger project map",
        "",
        "Generated by `scripts/build_map.py` from the code. Do not edit by hand. "
        "Format: `path` (lines): what it is. `defs`: public classes/functions with line numbers. "
        "`uses`: project files it imports. Longer reading: [PROJECT_GUIDE.md](PROJECT_GUIDE.md). "
        "Interactive version: `site/explore/index.html`.",
        "",
    ]
    for layer in data["layers"]:
        files = [f for f in data["files"] if f["layer"] == layer["id"]]
        if not files:
            continue
        out += [f"## {layer['title']}: {layer['about']}", ""]
        for f in files:
            out.append(f"- `{f['path']}` ({f['lines']}): {f['note']}")
            if f["layer"] not in ("tests", "site") and f["symbols"]:
                defs = ", ".join(f"{s['name']}:{s['line']}" for s in f["symbols"][:30])
                more = f", +{len(f['symbols']) - 30} more" if len(f["symbols"]) > 30 else ""
                out.append(f"  - defs: {defs}{more}")
            if f["layer"] not in ("tests", "site") and f["uses"]:
                out.append(
                    "  - uses: "
                    + ", ".join(
                        u.split("/", 1)[-1] if u.startswith("app/") else u for u in f["uses"]
                    )
                )
        out.append("")
    out += ["## Commands", ""]
    out += [
        f"- `{c['command']}`{'' if c['menu'] else ' (hidden)'}: {c['what']} (`{c['file']}`)"
        for c in data["commands"]
    ]
    out += ["", "## Database tables (🔒 = encrypted column)", ""]
    for t in data["tables"]:
        lock = f" 🔒 {', '.join(t['encrypted'])}" if t["encrypted"] else ""
        out.append(f"- `{t['name']}`: {t['about']}{lock}")
    out += ["", "## Request tours", ""]
    for t in data["tours"]:
        out.append(f"**{t['title']}** ({t['ask']})")
        out += [f"{i}. `{s['path']}`: {s['text']}" for i, s in enumerate(t["steps"], 1)]
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"  # exactly one final newline (pre-commit checks it)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="only report files without a note")
    args = parser.parse_args()
    data, missing = build()
    if missing:
        print("These files need a line in NOTES (scripts/build_map.py):")
        for m in missing:
            print("  ", m)
        return 1
    if args.check:
        print(f"OK: {data['totals']['files']} files have notes.")
        return 0
    JSON_OUT.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    MD_OUT.write_text(markdown(data), encoding="utf-8", newline="\n")
    # Windows checkouts may turn LF into CRLF; normalise so every machine builds identical bytes
    template = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    page = template.replace("/*__DATA__*/null", payload).replace(
        "__SCRIPT__", APP_JS.read_text(encoding="utf-8").replace("\r\n", "\n")
    )
    HTML_OUT.write_text(page, encoding="utf-8", newline="\n")
    print(
        f"Wrote {MD_OUT.relative_to(ROOT)}, {JSON_OUT.relative_to(ROOT)} and "
        f"{HTML_OUT.relative_to(ROOT)} ({data['totals']['files']} files)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
