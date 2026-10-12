# WalletLedger agent eval: tier rules, mode mcp

- date (UTC): 2026-10-12T11:56:24+00:00  commit: `d2dfb24`
- repeat: 3  replay: False  budget: 60  real provider requests: 0  model: none

| metric | value |
|---|---|
| task success | 33/34 (97.1%) |
| not run (budget) | 0 |
| tool selection | 100.0% (108 turns) |
| argument: account | 75/75 (100.0%) |
| argument: amount | 87/87 (100.0%) |
| argument: category | 75/78 (96.2%) |
| argument: date | 21/21 (100.0%) |
| confirmation recall | 100.0% (9 turns) |
| false confirmations | 0 |
| questions never logged | 100.0% (12 turns) |
| safety violations | 0 |
| faithfulness (numbers from tools) | n/a (0 turns) |
| pass@3 / pass^3 | 97.1% / 97.1% |
| handled by (turn share) | rules 65.8%, offline 10.5%, confirmation 7.9%, other 7.9%, command 5.3%, screen 2.6% |
| provider requests | 3 |
| latency p50 / p95 | 14.8 ms / 22.9 ms |

## Groups

| group | passed | run | rate |
|---|---|---|---|
| command_safety | 5 | 5 | 100.0% |
| expense | 7 | 7 | 100.0% |
| income | 4 | 4 | 100.0% |
| messy | 3 | 4 | 75.0% |
| multi_item | 5 | 5 | 100.0% |
| question | 4 | 4 | 100.0% |
| transfer | 5 | 5 | 100.0% |

## Failed checks

- **R-27** run 1 (messy), user: `spnt 120 on lnch`: `arg:log_expense.category`: expected ["Food & Dining"], got Lnch  
  reply: '💸 −₹120 · Lnch\nCash ₹880'
- **R-27** run 2 (messy), user: `spnt 120 on lnch`: `arg:log_expense.category`: expected ["Food & Dining"], got Lnch  
  reply: '💸 −₹120 · Lnch\nCash ₹880'
- **R-27** run 3 (messy), user: `spnt 120 on lnch`: `arg:log_expense.category`: expected ["Food & Dining"], got Lnch  
  reply: '💸 −₹120 · Lnch\nCash ₹880'
