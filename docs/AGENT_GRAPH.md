# Agentic StateGraph (branch `feat/agentic-graph`)

Goal: delete the hardcoded rules engine (`app/bot/nlu.py`, `orchestrator.py`, the regex layer in
`main.handle_incoming`) and let one LLM planner understand free text and pick tools. Edge cases
pause with LangGraph `interrupt()` and resume with `Command(resume=...)`.

Single agent, specialist tools. The ledger stays the source of truth; rules about money
(overdraw, amount > 0, future dates) stay in `ledger.py`, never in the prompt.

## What stays deterministic (no LLM)

- Slash commands (`/balance`, `/stats`, `/budget food 2000`, `/plan 50000 6`, ...) and every inline
  button. They are structured input, not natural language.
- Pasted API keys: detected by `ai_gateway.extract_api_keys`, saved, never sent to the LLM.
- HITL triggers (`guard` node), insufficient-balance buttons, templates, budget note.
- Statement (PDF) parsing.

## AgentState

```
chat_id      str
user_text    str                       # this turn's message
persona      "coach"|"budgeter"|"summary"|None   # from /coach etc.
messages     Annotated[list, add_messages]       # reset each turn, history reloaded from DB
context      dict                      # accounts+balances, default account, categories, budgets, today
step         int                       # planner rounds this turn (cap MAX_STEPS=5)
tool_runs    list[ToolRun]             # {id, name, args, result, error, error_kind}
reply_text   str
pending      dict|None                 # last interrupt payload (for Outcome)
pay_alternative dict|None
offline_reason str|None
```

## Nodes and edges

```
START → ingress
ingress ─(api key pasted / reply already set)→ renderer
ingress ────────────────────────────────────→ planner
planner ─(final text)───────────────────────→ renderer
planner ─(tool_calls)───────────────────────→ guard
planner ─(NoAPIKeyError / LLM failure)──────→ renderer   (fixed hint, nothing logged)
guard   ─────────────────────────────────────→ executor  (interrupt() inside if approval needed)
executor ─(any read/advice tool ran, or a recoverable error, and step < MAX)→ planner
executor ─(only writes / insufficient balance / step cap)──────────────────→ renderer
renderer → END
```

| Node | LLM | Job |
|---|---|---|
| ingress | no | Key paste short-circuit, `/coach` → persona, load `context` + last 20 messages, reset per-turn fields |
| planner | yes | One call: system prompt + context + messages + tool schema → tool_calls or final text |
| guard | no | `confirmation_reason` (transfer ≥ ₹5,000, any edit/delete) + budget overspend → one `interrupt()` per batch |
| executor | no | Injects `user_id`, runs tools via `tool_client`, `ToolMessage` per call (declined ones too), error kinds, `pay_alternative` |
| renderer | no | Planner text > `replies.compact` > `tool_summary`/templates; adds budget note |

Tool kinds: write = `log_expense log_income transfer_funds edit_transaction delete_transaction
set_category_budget set_default_account set_account_balance`; everything else is read/advice and
loops back to the planner so it can write the answer.

## HITL

- Interrupt payload: `{kind: "confirm", id, created_at, description, calls}`.
- Checkpointer: `InMemorySaver`, `thread_id = chat_id` (no new dependency; pending dies on restart,
  same as the old `session_store`). Swap for a Postgres/SQLite saver later.
- Buttons `ask:yes:<id>` / `ask:no:<id>` → `agent.resume_pending(chat_id, yes, id)`.
- TTL 5 min, checked against `created_at` before resuming.
- Typed reply while waiting → `agent.classify_decision` (small LLM call) → confirm / cancel / new.
  A new request cancels the pending one first.

## New tools (mcp_server + schema)

- `delete_transaction(user_id, transaction_id)` → `ledger.undo_transaction`
- `set_default_account(user_id, account_name)`
- `set_account_balance(user_id, account_name, balance)` → opening balance / adjustment entry

## Public agent API (used by main.py, callbacks, tests)

`process_user_interaction_ex(chat_id, text, attachments=None) -> Outcome`,
`process_user_interaction`, `resume_pending(chat_id, yes, pending_id=None) -> Outcome | None`,
`has_pending(chat_id)`, `cancel_pending(chat_id)`, `classify_decision(chat_id, text)`,
`Outcome`, `TOOLS_SCHEMA`, `confirmation_reason`, `CONFIRMATION_TRANSFER_THRESHOLD`,
`PENDING_ACTION_TTL`, `HISTORY_LIMIT`, `save_db_chat_message`, `get_db_conversation_history`,
`redact_api_keys`, `build_agent_graph`, `agent_app`.

## Helpers that survive nlu.py

- `app/bot/categories.py`: `canonical_category` + `CATEGORY_WORDS` (keeps budgets and expenses on
  the same category; also listed in the planner prompt).
- `app/bot/textutil.py`: `parse_amount` ("2k", "1.5 lakh") and `parse_goal` for slash-command
  arguments and the onboarding balance answer. Structured input only, not intent detection.

## Trade-offs

- Every free-text message needs an AI key (user's or server's). Without one, the bot answers with
  the key hint and logs nothing. Commands and buttons still work offline.
- 1 LLM call for a plain entry, 2 for questions/advice, +1 for a typed yes/no.
- Category names can vary between calls; `canonical_category` normalises them in the ledger tools.
