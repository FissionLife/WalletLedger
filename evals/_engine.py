"""The eval engine: seeds a throwaway database, drives the real chat router, records each turn.

Imported by ``evals.run_eval`` only after the environment is locked down (see that module).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import litellm
from sqlalchemy import func, select

from app.bot import agent, nlu
from app.bot import main as bot_main
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Account, ChatMessage, Transaction, User
from app.services import ledger
from app.services_ai import ai_gateway, mcp_server, tool_client
from evals import scoring

ROOT = Path(__file__).resolve().parent.parent


class Recorder:
    """Per-turn observations: tool calls, which path ran, provider requests."""

    def __init__(self, scrub, *, live: bool, replay: list[dict] | None, budget: int):
        self.scrub = scrub
        self.live = live
        self.replay = replay
        self.budget = budget
        self.real_requests = 0
        self.provider_errors = 0
        self.model: str | None = None
        self.reset_case()

    def reset_case(self) -> None:
        self.case_log: list[dict[str, Any]] = []
        self.case_requests = 0
        self.case_errors = 0
        self.reset_turn()

    def reset_turn(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.turn_requests = 0  # answered requests (the agent's own cost)
        self.turn_errors = 0  # provider errors (503 busy, 429 rate limit): quota, not agent

    # ---- wrappers ----------------------------------------------------------------------------
    def wrap_tool(self, original):
        async def call_tool(name: str, **args: Any) -> dict[str, Any]:
            entry = {"tool": name, "args": dict(args), "result": None, "error": None}
            self.calls.append(entry)
            try:
                entry["result"] = await original(name, **args)
            except Exception as exc:
                entry["error"] = str(exc)[:300]
                raise
            return entry["result"]

        return call_tool

    def wrap_path(self, original, label: str, when_none: bool = False):
        async def wrapper(*a, **kw):
            result = await original(*a, **kw)
            if (result is not None) != when_none:
                self.paths.append(label)
            return result

        return wrapper

    def wrap_completion(self, original):
        async def acompletion(*a, **kw):
            entry = {"model": kw.get("model"), "messages": self.scrub(kw.get("messages"))}
            if self.replay is not None:
                if not self.replay:
                    raise RuntimeError("eval replay: no more recorded responses for this case")
                saved = self.replay.pop(0)
                if saved.get("error"):
                    self.turn_errors += 1
                    self.case_errors += 1
                    raise litellm.ServiceUnavailableError(
                        saved["error"], "gemini", saved.get("model", "")
                    )
                self.turn_requests += 1
                self.case_requests += 1
                return litellm.ModelResponse(**saved["response"])
            if not self.live:
                self.turn_requests += 1  # an attempt in a rules case is counted against it
                self.case_requests += 1
                raise litellm.AuthenticationError("eval: AI disabled in rules tier", "gemini", "")
            self.real_requests += 1
            self.model = kw.get("model") or self.model
            try:
                response = await original(*a, **kw)
            except Exception as exc:
                self.turn_errors += 1
                self.case_errors += 1
                self.provider_errors += 1
                entry["error"] = self.scrub(f"{type(exc).__name__}: {str(exc)[:300]}")
                self.case_log.append(entry)
                raise
            self.turn_requests += 1
            self.case_requests += 1
            entry["response"] = self.scrub(response.model_dump())
            self.case_log.append(entry)
            return response

        return acompletion


# ---------------------------------------------------------------------------------- database
def _seed(chat_id: str, seed: dict[str, Any]) -> int:
    with SessionLocal() as db:
        user = ledger.get_or_create_user(db, chat_id)
        for name, balance in (seed.get("accounts") or {}).items():
            acc = ledger.get_or_create_account(db, user.id, name)
            acc.balance = float(balance)
        db.commit()
    today = datetime.now().date()
    for tx in seed.get("transactions") or []:
        when = (today - timedelta(days=int(tx.get("days_ago", 0)))).isoformat()
        if tx["type"] == "income":
            mcp_server.log_income(
                chat_id,
                tx["amount"],
                source_account=tx.get("account", "Bank"),
                category=tx.get("category", "Income"),
                date=when,
            )
        else:
            mcp_server.log_expense(
                chat_id,
                tx["amount"],
                tx.get("category", "Uncategorized"),
                merchant=tx.get("merchant"),
                account_name=tx.get("account", "Cash"),
                date=when,
            )
    for category, amount in (seed.get("budgets") or {}).items():
        mcp_server.set_category_budget(chat_id, category, amount)
    return _state(chat_id)["tx_count"]


def _state(chat_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if user is None:
            return {"balances": {}, "tx_count": 0, "history": []}
        balances = {
            a.name: round(a.balance, 2)
            for a in db.scalars(select(Account).where(Account.user_id == user.id))
        }
        count = db.scalar(select(func.count()).where(Transaction.user_id == user.id)) or 0
        history = [
            m.content for m in db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id))
        ]
    return {"balances": balances, "tx_count": int(count), "history": history}


# ---------------------------------------------------------------------------------- one turn
def _path(rec: Recorder, text: str, pending_before: bool, entered_agent: bool) -> str:
    if pending_before and agent.classify_reply(text):
        return "confirmation"
    for label in ("orchestrator", "persona", "llm", "rules"):
        if label in rec.paths:
            return label
    if not entered_agent:
        if text.strip().startswith("/"):
            return "command"
        if nlu.detect_screen(text) is not None:
            return "screen"
    return "other"


async def _turn(rec: Recorder, chat_id: str, text: str, baseline: int) -> dict[str, Any]:
    rec.reset_turn()
    pending_before = agent.session_store.get_pending(chat_id) is not None
    entered = {"agent": False}
    original_entry = bot_main.process_user_interaction_ex

    async def entry(*a, **kw):
        entered["agent"] = True
        return await original_entry(*a, **kw)

    started = time.perf_counter()
    with patch.object(bot_main, "process_user_interaction_ex", entry):
        reply = await bot_main.handle_incoming(chat_id, text)
    latency = (time.perf_counter() - started) * 1000
    path = _path(rec, text, pending_before, entered["agent"])
    if path == "llm" and not rec.live and rec.replay is None:
        path = "offline"  # the AI step ran with no key: the offline rules answered
    if path == "other" and (reply.text or "").startswith("🧠"):
        path = "persona"
    state = await asyncio.to_thread(_state, chat_id)
    return {
        "user": text,
        "reply_text": reply.text or "",
        "path": path,
        "needs_confirmation": any(b.data == "ask:yes" for row in reply.rows for b in row),
        "calls": rec.scrub(rec.calls),
        "balances": state["balances"],
        "new_transactions": state["tx_count"] - baseline,
        "provider_requests": rec.turn_requests,
        "provider_errors": rec.turn_errors,
        "latency_ms": round(latency, 1),
        "chat_history": state["history"],
    }


async def _run_case(rec: Recorder, case: dict[str, Any], k: int) -> dict[str, Any]:
    chat_id = f"eval-{case['id']}-{k}-{secrets.token_hex(3)}"
    baseline = await asyncio.to_thread(_seed, chat_id, case.get("seed") or {})
    observed = []
    for turn in case["turns"]:
        try:
            observed.append(await _turn(rec, chat_id, turn["user"], baseline))
        except Exception as exc:  # a crash is a failed turn, not a crashed eval
            observed.append({"user": turn["user"], "reply_text": f"EVAL CRASH: {exc!r}"[:300],
                             "path": "crash", "calls": rec.scrub(rec.calls),
                             "provider_requests": rec.turn_requests})  # fmt: skip
            break
    return scoring.score_case(case, observed, datetime.now().date())


# ---------------------------------------------------------------------------------- the run
def _load(path: str, tier: str, only: list[str]) -> list[dict[str, Any]]:
    cases = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if tier != "all":
        cases = [c for c in cases if c["tier"] == tier]
    if only:
        cases = [c for c in cases if c["id"] in only]
    rules = [c for c in cases if c["tier"] == "rules"]
    llm = sorted(
        (c for c in cases if c["tier"] == "llm"), key=lambda c: (c.get("priority", 3), c["id"])
    )
    return rules + llm


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


async def _run_all(args, scrub) -> tuple[list[dict], Recorder]:
    init_db()
    ai_gateway.reset_rotation_state()
    if args.replay and not os.environ.get("GEMINI_API_KEYS"):
        # Replay serves saved answers; the gateway only needs *a* key to try (never sent anywhere).
        os.environ["GEMINI_API_KEYS"] = ",".join("AIza" + str(i) * 35 for i in range(10))
    rec = Recorder(scrub, live=False, replay=None, budget=args.llm_budget)
    recordings = Path(args.recordings)
    results = []
    settings.tool_mode = args.mode
    await tool_client.start()
    try:
        with (
            patch.object(tool_client, "call_tool", rec.wrap_tool(tool_client.call_tool)),
            patch.object(agent, "_nlu_analysis", rec.wrap_path(agent._nlu_analysis, "rules")),
            patch.object(agent, "_run_llm_analysis", rec.wrap_path(agent._run_llm_analysis, "llm")),
            patch.object(agent, "_orchestrate", rec.wrap_path(agent._orchestrate, "orchestrator")),
            patch.object(litellm, "acompletion", rec.wrap_completion(litellm.acompletion)),
        ):
            for case in _load(args.golden, args.tier, args.case):
                is_llm = case["tier"] == "llm"
                runs = []
                for k in range(1, args.repeat + 1):
                    rec.live = is_llm and not args.replay
                    rec.replay = None
                    file = recordings / f"{case['id']}.r{k}.json"
                    if is_llm and args.replay:
                        if not file.exists():
                            break
                        rec.replay = json.loads(file.read_text(encoding="utf-8"))
                    remaining = args.llm_budget - rec.real_requests
                    if rec.live and remaining < int(case.get("max_provider_requests") or 0):
                        print(f"  {case['id']} run {k}: not run (budget left {remaining})")
                        break
                    rec.reset_case()
                    result = await _run_case(rec, case, k)
                    if rec.live:
                        recordings.mkdir(parents=True, exist_ok=True)
                        file.write_text(
                            json.dumps(rec.case_log, indent=1, ensure_ascii=False, default=str),
                            encoding="utf-8",
                        )
                    runs.append(result)
                    mark = "PASS" if result["passed"] else "FAIL"
                    print(
                        f"  {case['id']:<5} run {k}: {mark}  ({result['provider_requests']} AI answers, "
                        f"{rec.case_errors} provider errors)"
                    )
                results.append(scoring.case_result(case, runs or None))
    finally:
        await tool_client.stop()
    return results, rec


def run(args, scrub) -> int:
    results, rec = asyncio.run(_run_all(args, scrub))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "local_date": date.today().isoformat(),
        "commit": _commit(),
        "tier": args.tier,
        "mode": args.mode,
        "repeat": args.repeat,
        "replay": args.replay,
        "llm_budget": args.llm_budget,
        "real_provider_requests": rec.real_requests,
        "provider_errors": rec.provider_errors,
        "model": rec.model,
        "golden": Path(args.golden).name,
    }
    m = scoring.metrics(results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = scrub({"meta": meta, "metrics": m, "results": results})
    text = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
    name = f"{args.tier}-{args.mode}" + ("-replay" if args.replay else "")
    (out / f"report-{stamp}-{name}.json").write_text(text, encoding="utf-8")
    (out / f"latest-{name}.json").write_text(text, encoding="utf-8")
    md = scoring.render_markdown(m, results, meta)
    (out / f"report-{stamp}-{name}.md").write_text(scrub(md), encoding="utf-8")
    print(f"\n{m['cases_passed']}/{m['cases_run']} cases passed "
          f"({m['not_run']} not run); real AI requests: {rec.real_requests}")  # fmt: skip
    print(f"report: {out / f'report-{stamp}-{name}.md'}")
    return 0
