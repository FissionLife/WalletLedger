# WalletLedger agent eval: tier llm, mode direct

- date (UTC): 2026-10-12T16:41:31+00:00  commit: `142d61e`
- repeat: 1  replay: False  budget: 25  real provider requests: 18 (provider errors: 13)  model: gemini/gemini-flash-latest

| metric | value |
|---|---|
| task success | 3/3 (100.0%) |
| not run (budget) | 0 |
| tool selection | 100.0% (3 turns) |
| confirmation recall | n/a (0 turns) |
| false confirmations | 0 |
| questions never logged | 100.0% (2 turns) |
| safety violations | 0 |
| faithfulness (numbers from tools) | 100.0% (1 turns) |
| handled by (turn share) | llm 66.7%, persona 33.3% |
| provider requests | 5 |
| latency p50 / p95 | 34447.1 ms / 56209.9 ms |

## Groups

| group | passed | run | rate |
|---|---|---|---|
| llm_goal | 2 | 2 | 100.0% |
| llm_persona | 1 | 1 | 100.0% |

## Failed checks

None.
