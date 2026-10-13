# WalletLedger agent eval: tier rules, mode direct

- date (UTC): 2026-10-12T17:23:48+00:00  commit: `e3b3058`
- repeat: 1  replay: False  budget: 60  real provider requests: 0 (provider errors: 0)  model: none

| metric | value |
|---|---|
| task success | 33/34 (97.1%) |
| not run (budget) | 0 |
| tool selection | 100.0% (36 turns) |
| argument: account | 25/25 (100.0%) |
| argument: amount | 29/29 (100.0%) |
| argument: category | 25/26 (96.2%) |
| argument: date | 7/7 (100.0%) |
| confirmation recall | 100.0% (3 turns) |
| false confirmations | 0 |
| questions never logged | 100.0% (4 turns) |
| safety violations | 0 |
| faithfulness (numbers from tools) | n/a (0 turns) |
| handled by (turn share) | rules 65.8%, offline 10.5%, confirmation 7.9%, other 7.9%, command 5.3%, screen 2.6% |
| provider requests | 1 |
| latency p50 / p95 | 31.2 ms / 59.3 ms |

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
