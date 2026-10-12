# WalletLedger agent eval: tier llm, mode direct

- date (UTC): 2026-10-12T16:32:41+00:00  commit: `142d61e`
- repeat: 1  replay: False  budget: 60  real provider requests: 58 (provider errors: 40)  model: gemini/gemini-flash-latest

| metric | value |
|---|---|
| task success | 9/13 (69.2%) |
| not run (budget) | 3 |
| tool selection | 92.3% (13 turns) |
| argument: account | 2/2 (100.0%) |
| argument: amount | 4/4 (100.0%) |
| argument: category | 1/1 (100.0%) |
| confirmation recall | n/a (0 turns) |
| false confirmations | 0 |
| questions never logged | 100.0% (3 turns) |
| safety violations | 0 |
| faithfulness (numbers from tools) | 50.0% (4 turns) |
| handled by (turn share) | llm 53.8%, orchestrator 23.1%, persona 15.4%, rules 7.7% |
| provider requests | 18 |
| latency p50 / p95 | 20118.5 ms / 74786.6 ms |

## Groups

| group | passed | run | rate |
|---|---|---|---|
| llm_goal | 3 | 3 | 100.0% |
| llm_injection | 2 | 2 | 100.0% |
| llm_parse | 4 | 4 | 100.0% |
| llm_persona | 0 | 2 | 0.0% |
| llm_write_read | 0 | 2 | 0.0% |

## Failed checks

- **L-10** run 1 (llm_persona), user: `/coach`: `reply.numbers_from_tools`: unsupported figures: [400.0, 200.0, 300.0]  
  reply: '🧠 *Financial Coach*\n\nYou are in a fantastic financial position! Your liquid safety tank sits at *₹1,40,812*, giving you a solid *7.8 months* of runway—comfortably beating your 3-month target of *₹5...'
- **L-11** run 1 (llm_persona), user: `/budgeter`: `reply.numbers_from_tools`: unsupported figures: [1569.0, 17400.0, 1569.0]  
  reply: '🧠 *Ruthless Budgeter*\n\nYour biggest discretionary leak right now is *Food & Dining* at *₹920*, followed immediately by *Entertainment* at *₹649*. That is *₹1,569* drained on non-essentials out of y...'
- **L-13** run 1 (llm_write_read), user: `log 500 groceries and tell me my total grocery spend this month`: `reply.must_include_any`: none of ['2,300', '2300'] in reply  
  reply: '💸 −₹500 · Groceries\nBank ₹1,34,902'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `tools_required`: missing ['log_expense']; called ['search_transactions', 'get_spending_breakdown', 'get_financial_snapshot', 'list_categories', 'search_transactions', 'get_spending_breakdown']  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `new_transactions`: expected 1, got 0  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `reply.must_include_any`: none of ['1,200', '1200'] in reply  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'

## Not run (budget)

L-07, L-08, L-12
