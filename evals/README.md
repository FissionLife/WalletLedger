# WalletLedger agent evaluation

Offline-first evaluation of the chat agent against a 50-case golden dataset.
Method, metrics and latest results: `docs/EVALUATION.md` (published on the site).

```bash
uv run python -m evals.run_eval --tier rules                    # 34 free cases, 0 AI calls
uv run python -m evals.run_eval --tier rules --mode mcp         # same, tools through the MCP server
uv run python -m evals.run_eval --tier rules --repeat 3         # consistency (pass^3)
uv run python -m evals.run_eval --tier llm --llm-budget 60      # EVAL_GEMINI_KEYS=key1,key2 in .env or the shell
uv run python -m evals.run_eval --tier llm --replay             # re-score saved AI answers, 0 calls
```

## Files
| file | what |
|---|---|
| `golden.jsonl` | the ground truth: one JSON object per line, 50 cases |
| `run_eval.py` | runner: seeds a throwaway SQLite DB, drives the bot, records what happened |
| `scoring.py` | compares a recorded run with the expectations; computes metrics; writes reports |
| `recordings/` | raw AI responses per case (`<id>.r<k>.json`), for free re-scoring with `--replay` |
| `reports/` | `report-<UTC timestamp>-<tier>-<mode>.md` and `.json`; `latest-<tier>-<mode>.json` |

## Golden case format (one line of `golden.jsonl`)
```json
{"id": "R-01", "tier": "rules", "group": "expense", "priority": 1, "max_provider_requests": 0,
 "note": "why this case exists",
 "seed": {"accounts": {"Bank": 20000, "Cash": 1000},
          "transactions": [{"type": "expense", "amount": 450, "category": "Food & Dining",
                            "account": "Bank", "merchant": "Swiggy", "days_ago": 3}],
          "budgets": {"Food & Dining": 6000}},
 "turns": [{"user": "spent 200 on chai",
            "expect": {"path": "rules",
                       "calls": [{"tool": "log_expense",
                                  "args": {"amount": 200, "category": "Food & Dining", "account_name": "Cash"}}],
                       "tools_required": [], "tools_forbidden": ["transfer_funds"],
                       "needs_confirmation": false,
                       "ledger_after": {"balances": {"Cash": 800, "Bank": 20000}, "new_transactions": 1},
                       "reply": {"must_include_any": ["200"], "must_include_all": [],
                                 "must_not_include": ["Traceback"], "max_words": 60,
                                 "numbers_from_tools": false},
                       "chat_history_must_not_include": []}}]}
```

Field rules (every `expect` field is optional; absent = not checked):
- `tier`: `rules` (must work with no AI key; the runner blocks every provider request) or `llm`
  (needs a Gemini key). A rules case may allow blocked attempts via `max_provider_requests`
  (R-30: the bot tests a pasted key live before saving it).
- `group`: expense, income, multi_item, transfer, question, messy, command_safety,
  llm_parse, llm_goal, llm_persona, llm_write_read, llm_injection.
- `priority`: 1 (run first) .. 3. LLM cases run in priority order until the budget is used.
- `max_provider_requests`: AI answers the case may use (the agent's own cost). Provider errors
  (503 busy, 429 rate limit) are not the agent's fault: they count toward `--llm-budget` and are
  reported separately, but do not fail a case.
- `seed`: applied to a brand-new chat id before turn 1. Default accounts (a new user always gets
  `Cash` 0 and `Bank` 0) are overwritten by `accounts`. Seeded transactions go through the ledger, so
  balances move. **`accounts` are the balances BEFORE seeded transactions are applied.**
- `path`: how the turn was handled: `command` (a /command or button-like screen), `offline` (the AI step ran
  without a key and the offline rules answered), `screen`
  (plain words that open a screen, e.g. "how much did I spend on food this month"), `rules`
  (nlu.py read it, no AI), `llm` (one-shot AI analysis), `orchestrator` (multi-step AI loop),
  `confirmation` (a yes/no answer to a pending action), `persona`, `other`.
  A list means "any of these".
- `calls`: the exact ordered list of tool calls this turn (only these tools, this order). `args`
  are partial: only listed keys are compared. Use `tools_required` / `tools_forbidden` instead when the
  exact sequence may legitimately vary (LLM cases).
- Arg / balance comparison: numbers within 0.01; strings case-insensitive and trimmed; a JSON list
  means "any of these"; the string `"$TODAY"` / `"$TODAY-1"` means that ISO date (compared on the
  first 10 chars); `null` means the key must be absent or null.
- `needs_confirmation`: the reply shows the Yes / Cancel buttons (nothing was changed yet).
- `ledger_after.balances`: every listed account's balance after this turn (others unchecked).
  `new_transactions`: transactions created since the seed finished (cumulative over turns).
- `reply`: checks on the reply text. `numbers_from_tools`: every rupee figure in the reply
  (₹ / Rs / INR amounts, and plain numbers ≥ 100) must appear in this turn's tool results or the
  ledger balances (±1, or ±1% for figures ≥ 1000), or be a sum/difference of 2-3 of those
  figures (arithmetic on real data). Invented targets ("save ~₹400") count as unsupported.
- `chat_history_must_not_include`: strings that must not be stored in `chat_messages` for this chat.

## Safety rules of the runner
- Always a throwaway SQLite file; `WALLETLEDGER_TESTING=1` and `LITELLM_MODE=PRODUCTION` are set
  before importing the app, so the real `.env` is never read. `TELEGRAM_BOT_TOKEN` is blanked.
- Tier `rules`: every AI key variable is blanked and `litellm.acompletion` is replaced by a stub
  that counts the attempt and raises (no network).
- Tier `llm`: keys come only from `EVAL_GEMINI_KEYS` (the shell, else that single line of the
  git-ignored `.env`; nothing else in `.env` is read), copied into `GEMINI_API_KEYS` for this process. They are never written to disk, printed, or included in reports/recordings
  (the runner scrubs anything key-shaped before writing). `DYNAMIC_MODELS=false`.
- The budget (`--llm-budget`) counts real provider requests (retries and model fallbacks included).
  A case is skipped (reported as `not_run`) when the remaining budget is below its
  `max_provider_requests`.
