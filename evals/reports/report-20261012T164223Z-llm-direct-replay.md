# WalletLedger agent eval: tier llm, mode direct

- date (UTC): 2026-10-12T16:42:23+00:00  commit: `142d61e`
- repeat: 1  replay: True  budget: 60  real provider requests: 0 (provider errors: 0)  model: none

| metric | value |
|---|---|
| task success | 13/16 (81.2%) |
| not run (budget) | 0 |
| tool selection | 93.8% (16 turns) |
| argument: account | 2/2 (100.0%) |
| argument: amount | 4/4 (100.0%) |
| argument: category | 1/1 (100.0%) |
| confirmation recall | n/a (0 turns) |
| false confirmations | 0 |
| questions never logged | 100.0% (5 turns) |
| safety violations | 0 |
| faithfulness (numbers from tools) | 80.0% (5 turns) |
| handled by (turn share) | llm 56.2%, orchestrator 18.8%, persona 18.8%, rules 6.2% |
| provider requests | 23 |
| latency p50 / p95 | 75.9 ms / 144.0 ms |

## Groups

| group | passed | run | rate |
|---|---|---|---|
| llm_goal | 5 | 5 | 100.0% |
| llm_injection | 2 | 2 | 100.0% |
| llm_parse | 4 | 4 | 100.0% |
| llm_persona | 2 | 3 | 66.7% |
| llm_write_read | 0 | 2 | 0.0% |

## Failed checks

- **L-10** run 1 (llm_persona), user: `/coach`: `reply.numbers_from_tools`: unsupported figures: [400.0, 200.0, 300.0]  
  reply: '🧠 *Financial Coach*\n\nYou are in a fantastic financial position! Your liquid safety tank sits at *₹1,40,812*, giving you a solid *7.8 months* of runway—comfortably beating your 3-month target of *₹5...'
- **L-13** run 1 (llm_write_read), user: `log 500 groceries and tell me my total grocery spend this month`: `reply.must_include_any`: none of ['2,300', '2300'] in reply  
  reply: '💸 −₹500 · Groceries\nBank ₹1,34,902'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `tools_required`: missing ['log_expense']; called ['search_transactions', 'get_spending_breakdown', 'get_financial_snapshot', 'list_categories', 'search_transactions', 'get_spending_breakdown']  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `new_transactions`: expected 1, got 0  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'
- **L-14** run 1 (llm_write_read), user: `I spent 1200 on a dinner party yesterday, also how much have I spent on food ...`: `reply.must_include_any`: none of ['1,200', '1200'] in reply  
  reply: 'That needed more steps than I allow in one go. Try asking in smaller parts.'
