# Graph Report - WalletLedger  (2026-10-16)

## Corpus Check
- 153 files · ~335,426 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 7, .css 2, .example 1)

## Summary
- 2786 nodes · 7881 edges · 145 communities (113 shown, 32 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 459 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `805da3d4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- init_db
- mcp_server.py
- agent.py
- model_catalog.py
- tool_client.py
- time
- tool
- db.py
- complete
- behaviour
- get_or_create_user
- test_bot_ui.py
- dashboard.js
- charts.py
- reset_rotation_state
- _engine.py
- .add
- asyncio
- build_candidates
- execute_tool
- setup_wizard.py
- argparse
- .say
- telegram.py
- FakeLLM
- undo_transaction
- ask_llm
- guardrails.py
- ai_gateway.py
- ConfirmationTests
- json
- test_import_logic.py
- export_csv
- analytics.py
- ui.py
- handle_incoming
- Settings
- replies.py
- 8. Three walkthroughs
- test_money_logic.py
- .say
- apply_profile
- save_db_chat_message
- Query
- .get
- FakeConsole
- prompts.py
- crypto.py
- read_env
- map_app.js
- keys.py
- handle_text
- start
- main.py
- merchant_from_narration
- test_statement_formats.py
- protect_data.py
- health.py
- record_transaction
- report
- package.json
- run
- firstrun.py
- Any
- transaction_parser.py
- AgentLoopTests
- bot/main.py
- parse_receipt_text
- seed
- OnboardingTests
- _webhook
- WalletLedger project guide
- AllKeysExhaustedError
- test_multi_bot.py
- 5. The parts, one by one
- inspect_statement.py
- budget_status
- webhook_secret
- decrypt_text
- _parse_app_blocks
- extract_api_keys
- _parse_bank_table
- main
- FileAndImportTests
- TestTelegramHelpers
- app.js
- BuildTests
- BotTestCase
- clock.py
- SetupStateTests
- _RotationState
- PeriodTests
- TunnelHelperTests
- read_profile
- .check
- validate_init_data
- month_pace
- FakeBot
- build_map.py
- _ConflictFilter
- WalletLedger Architecture
- parse_statement_file
- project.devprune.json
- LinkTests
- AccessControlTests
- ProjectMapTests
- ScriptTests
- Data Storage and Security
- SqliteHardeningTests
- WalletLedger project map
- build_docs.py
- CloudflareFilesTests
- canonical_category
- best_model
- README.md
- On a server (always on)
- Evaluating the AI agent
- WalletLedger
- io
- rank_models
- How WalletLedger works, in plain words
- model_chain
- WalletLedger
- pick_best
- .complete
- parse_provider_and_key
- Running WalletLedger with Cloudflare
- redact_secrets
- Live demo script (about 8 minutes)
- Code map
- WalletLedger agent evaluation
- WalletLedger agent eval: tier llm, mode direct
- .test_confirming_runs_every_call_from_that_message
- MiniAppAuthTests
- _keyword_category
- WalletLedger agent eval: tier rules, mode direct
- WalletLedger agent eval: tier rules, mode mcp
- WalletLedger agent eval: tier llm, mode direct
- WalletLedger agent eval: tier llm, mode direct
- WalletLedger agent eval: tier rules, mode direct
- WalletLedger landing page
- _is_essential
- SiteIntegrationTests
- AGENTS.md
- TOOL_MODE.md

## God Nodes (most connected - your core abstractions)
1. `FakeLLM` - 141 edges
2. `tool()` - 79 edges
3. `get_or_create_user()` - 71 edges
4. `record_transaction()` - 66 edges
5. `init_db()` - 52 edges
6. `User` - 44 edges
7. `handle_incoming()` - 43 edges
8. `Reply` - 43 edges
9. `execute_tool()` - 43 edges
10. `report()` - 42 edges

## Surprising Connections (you probably didn't know these)
- `5.2 The agent (`agent.py`)` --references--> `process_user_interaction_ex()`  [INFERRED]
  docs/PROJECT_GUIDE.md → app/bot/agent.py
- `Trade-offs` --references--> `canonical_category()`  [INFERRED]
  docs/AGENT_GRAPH.md → app/bot/categories.py
- `How a run works` --references--> `handle_incoming()`  [INFERRED]
  docs/EVALUATION.md → app/bot/main.py
- `5.6b Screens and buttons (`views.py`, `ui.py`, `callbacks.py`)` --references--> `Reply`  [INFERRED]
  docs/PROJECT_GUIDE.md → app/bot/ui.py
- `New tools (mcp_server + schema)` --references--> `undo_transaction()`  [INFERRED]
  docs/AGENT_GRAPH.md → app/services/ledger.py

## Import Cycles
- 3-file cycle: `app/bot/callbacks.py -> app/bot/main.py -> app/bot/telegram.py -> app/bot/callbacks.py`
- 3-file cycle: `app/bot/main.py -> app/bot/telegram.py -> app/bot/profile.py -> app/bot/main.py`

## Communities (145 total, 32 thin omitted)

### Community 0 - "init_db"
Cohesion: 0.07
Nodes (13): init_db(), ScriptTests, SetupScriptTests, GoldenFileTests, RulesRunTests, auth_error(), auth_error(), _call() (+5 more)

### Community 1 - "mcp_server.py"
Cohesion: 0.06
Nodes (36): encrypt_vault(), delete_transaction(), edit_transaction(), _expected_errors_visible(), financial_advice_bundle(), get_financial_snapshot(), get_pipe_balances(), get_spending_breakdown() (+28 more)

### Community 2 - "agent.py"
Cohesion: 0.11
Nodes (10): _amount_of(), _budget_overage_reason(), confirmation_reason(), _describe_call(), _find_user(), guard_node(), _load_context(), _pending_id() (+2 more)

### Community 3 - "model_catalog.py"
Cohesion: 0.16
Nodes (16): _fetch_anthropic(), _fetch_deepseek(), _fetch_gemini(), _fetch_groq(), _fetch_mistral(), _fetch_ollama(), _fetch_openai(), _fetch_openai_style() (+8 more)

### Community 4 - "tool_client.py"
Cohesion: 0.06
Nodes (21): _add_missing_columns(), _add_missing_indexes(), available_tools(), call_tool(), _error_text(), is_connected(), mode(), _result_data() (+13 more)

### Community 5 - "time"
Cohesion: 0.18
Nodes (9): _dotenv_value(), find_cloudflared(), main(), named_command(), parse_tunnel_url(), quick_command(), server_env(), _stop() (+1 more)

### Community 6 - "tool"
Cohesion: 0.10
Nodes (11): has_pending(), tool(), AgentTestCase, chat(), run(), TestAccountSelection, TestApiKeysInChat, TestConfirmationFlow (+3 more)

### Community 7 - "db.py"
Cohesion: 0.09
Nodes (16): get_db(), Account, Base, Category, Merchant, Subscription, Transaction, User (+8 more)

### Community 8 - "complete"
Cohesion: 0.11
Nodes (15): check(), _classify(), complete(), _explain_rejection(), _is_model_problem(), KeyCheck, _short_error(), _short_error_raw() (+7 more)

### Community 9 - "behaviour"
Cohesion: 0.22
Nodes (12): Base, fake(), CompletionFallbackTests, behaviour(), behaviour(), fake(), behaviour(), behaviour() (+4 more)

### Community 10 - "get_or_create_user"
Cohesion: 0.13
Nodes (13): _ensure_user(), get_or_create_user(), AnalyticsFixTests, balance(), BalanceTests, add(), count_transactions(), DashboardFixTests (+5 more)

### Community 11 - "test_bot_ui.py"
Cohesion: 0.16
Nodes (10): _b64(), base_url(), dashboard_url(), is_https(), _key(), make_token(), read_token(), _unb64() (+2 more)

### Community 12 - "dashboard.js"
Cohesion: 0.17
Nodes (42): api(), bucketRange(), drawAccounts(), drawBudgets(), drawCategories(), drawHeatmap(), drawIncome(), drawLists() (+34 more)

### Community 13 - "charts.py"
Cohesion: 0.15
Nodes (22): _blend(), chart_accounts(), chart_budgets(), chart_categories(), chart_heatmap(), chart_hours(), chart_merchants(), chart_monthly() (+14 more)

### Community 14 - "reset_rotation_state"
Cohesion: 0.10
Nodes (6): default_model(), reset_rotation_state(), resolve_model(), GatewayTestCase, TestRoutingHelpers, ContractTestCase

### Community 15 - "_engine.py"
Cohesion: 0.06
Nodes (34): _commit(), _load(), _path(), Recorder, wrapper(), wrapper(), run(), _run_all() (+26 more)

### Community 16 - ".add"
Cohesion: 0.12
Nodes (11): reset(), text_response(), tools_response(), agent_waits(), balances(), EverydayChatTests, last_ids(), NewUserTests (+3 more)

### Community 17 - "asyncio"
Cohesion: 0.09
Nodes (30): bar(), change(), day(), inr(), plural(), short(), balance(), balance_text() (+22 more)

### Community 18 - "build_candidates"
Cohesion: 0.09
Nodes (12): build_candidates(), _candidate_models(), _env(), get_user_api_keys(), _grouped_rotated(), has_server_keys(), KeyCandidate, _model_for() (+4 more)

### Community 19 - "execute_tool"
Cohesion: 0.13
Nodes (10): execute_tool(), balance_of(), BlockedSpendButtonsTests, BudgetChatTests, BudgetOverageConfirmTests, BudgetTrackingTests, fund(), new_user() (+2 more)

### Community 20 - "setup_wizard.py"
Cohesion: 0.19
Nodes (14): _ask_token(), check_token(), Console, detect_chat_id(), doctor(), run_wizard(), step_ai_key(), step_database() (+6 more)

### Community 21 - "argparse"
Cohesion: 0.20
Nodes (7): _keys_from_env_file(), main(), parse_args(), _prepare_env(), scrub(), main(), show()

### Community 22 - ".say"
Cohesion: 0.17
Nodes (5): Base, MoneyScreensTests, NavigationTests, StatsTests, UndoAndConfirmTests

### Community 23 - "telegram.py"
Cohesion: 0.08
Nodes (14): should_delete_message(), upload_type(), build_router(), deliver(), keyboard(), on_callback(), on_document(), on_other() (+6 more)

### Community 24 - "FakeLLM"
Cohesion: 0.13
Nodes (9): ChatMessage, FakeLLM, chat(), GuardTestCase, InputGuardrailTests, OffTopicTests, OutputGuardrailTests, ToolGuardrailTests (+1 more)

### Community 25 - "undo_transaction"
Cohesion: 0.11
Nodes (8): run(), undo_transaction(), tx(), ago(), Base, LedgerUndoAndDateTests, ReportTests, undo()

### Community 26 - "ask_llm"
Cohesion: 0.09
Nodes (14): ask_llm(), ask_persona(), auth_error(), fake_response(), rate_limit_error(), run(), TestRotationAndFallback, CommandHintTests (+6 more)

### Community 27 - "guardrails.py"
Cohesion: 0.10
Nodes (13): as_json(), check_call(), check_input(), _close(), leaks(), _luhn(), mask_pii(), card() (+5 more)

### Community 28 - "ai_gateway.py"
Cohesion: 0.10
Nodes (24): ApiKey, activate_api_key(), add_api_key(), add_api_keys_from_text(), add_validated_keys(), deactivate_api_key(), decrypt_api_key(), delete_api_key() (+16 more)

### Community 29 - "ConfirmationTests"
Cohesion: 0.18
Nodes (6): balance(), ButtonTests, chat(), ConfirmationTests, run(), seed()

### Community 30 - "json"
Cohesion: 0.15
Nodes (11): AgentState, build_agent_graph(), executor_node(), ingress_node(), _parse_args(), _pay_alternative(), planner_node(), route_after_executor() (+3 more)

### Community 31 - "test_import_logic.py"
Cohesion: 0.21
Nodes (14): answer_pending_import(), BalanceChoiceTests, bank(), count(), day(), DuplicateTests, fund(), new_chat() (+6 more)

### Community 32 - "export_csv"
Cohesion: 0.14
Nodes (15): csv_safe(), build_query(), _chat_from(), _csv_list(), dashboard_data(), work(), export_csv(), load() (+7 more)

### Community 33 - "analytics.py"
Cohesion: 0.15
Nodes (20): biggest_expenses(), _bucket(), by_account(), calendar_heatmap(), category_breakdown(), category_by_period(), _change(), _expenses() (+12 more)

### Community 34 - "ui.py"
Cohesion: 0.14
Nodes (16): Btn, cancel_row(), chart_nav_rows(), chart_rows(), confirm_rows(), history_rows(), import_rows(), keys_rows() (+8 more)

### Community 35 - "handle_incoming"
Cohesion: 0.08
Nodes (32): _go(), handle_callback(), keys_screen(), _pay_from_other(), answer_pending_action(), handle_incoming(), _reply_for(), _view_command() (+24 more)

### Community 36 - "Settings"
Cohesion: 0.11
Nodes (5): Settings, cfg(), ModeSelectionTests, cfg(), SettingsParsingTests

### Community 37 - "replies.py"
Cohesion: 0.15
Nodes (11): _budget_note_for(), renderer_node(), _template_response_dict(), _balance_line(), compact(), confirm_prompt(), friendly_error(), _line() (+3 more)

### Community 38 - "8. Three walkthroughs"
Cohesion: 0.25
Nodes (4): parse_args(), stats(), 8. Three walkthroughs, FormattingTests

### Community 39 - "test_money_logic.py"
Cohesion: 0.15
Nodes (11): parse_period(), AverageTests, CategoryResolverTests, ComparisonTests, frozen(), HeatmapAndTruncationTests, PlanningTests, spend() (+3 more)

### Community 40 - ".say"
Cohesion: 0.13
Nodes (12): AQKeyTests, call(), rejected(), AsyncMock_raise(), Base, HealthTests, ok_response(), provider() (+4 more)

### Community 41 - "apply_profile"
Cohesion: 0.15
Nodes (9): apply_profile(), commands(), validate(), _publish_profile(), ApplyTests, fake_bot(), run(), StartupHookTests (+1 more)

### Community 42 - "save_db_chat_message"
Cohesion: 0.19
Nodes (6): get_db_conversation_history(), _history_dicts(), process_user_interaction(), redact_api_keys(), save_db_chat_message(), Public agent API (used by main.py, callbacks, tests)

### Community 43 - "Query"
Cohesion: 0.14
Nodes (6): run(), _inr(), Query, resolve_filters(), summary(), 5.6 Analytics and charts (`analytics.py`, `charts.py`)

### Community 44 - ".get"
Cohesion: 0.15
Nodes (4): Base, PageAndAuthTests, ReportTests, TransactionsAndExportTests

### Community 45 - "FakeConsole"
Cohesion: 0.18
Nodes (4): is_weak_secret(), FakeConsole, me(), WizardTests

### Community 46 - "prompts.py"
Cohesion: 0.14
Nodes (10): build_planner_prompt(), build_system_prompt(), detect_mode(), _format_context(), get_persona(), list_modes(), Mode, Persona (+2 more)

### Community 47 - "crypto.py"
Cohesion: 0.10
Nodes (13): all_secrets(), decrypt_vault(), derive_key(), _legacy_vault(), legacy_vault_fernet(), _multi(), multi_fernet(), newest_fernet() (+5 more)

### Community 48 - "read_env"
Cohesion: 0.14
Nodes (9): _format(), _private(), read_env(), set_values(), _value(), apply_defaults(), step_secret(), EnvFileTests (+1 more)

### Community 49 - "map_app.js"
Cohesion: 0.26
Nodes (21): base(), byPath, chips(), commandsView(), D, dataView(), drawDetail(), drawTabs() (+13 more)

### Community 50 - "keys.py"
Cohesion: 0.19
Nodes (14): _admin_stats(), _bad_number(), edit_key(), _fallback_line(), handle_admin_command(), handle_key_command(), keys_text(), _position() (+6 more)

### Community 51 - "handle_text"
Cohesion: 0.22
Nodes (6): handle_document(), handle_text(), make_pdf(), run(), TestCommands, TestStatementImport

### Community 52 - "start"
Cohesion: 0.15
Nodes (8): running_bots(), start(), stop(), cycle(), StartupTests, go(), LifecycleTests, go()

### Community 53 - "main.py"
Cohesion: 0.18
Nodes (6): health(), lifespan(), root(), start_dev(), SecretKeyTests, start()

### Community 54 - "merchant_from_narration"
Cohesion: 0.20
Nodes (9): _display_name(), _is_id_word(), _is_noise_word(), merchant_from_narration(), _merchant_from_vpa(), _name_from_phrase(), _narration_vpa(), _segment_name() (+1 more)

### Community 55 - "test_statement_formats.py"
Cohesion: 0.14
Nodes (7): detect_statement_format(), parse_statement_text(), BankTableTests, by_merchant(), FormatDetectionTests, SmsAndGenericTests, UpiAppStatementTests

### Community 56 - "protect_data.py"
Cohesion: 0.19
Nodes (9): _batches(), _confirm(), encrypt(), _existing(), _key_ok(), main(), rotate(), status() (+1 more)

### Community 57 - "health.py"
Cohesion: 0.14
Nodes (8): weak_secret_key(), describe_database(), ai_path(), AIPath, setup_notes(), setup_problems(), user_status_text(), HealthNotesTests

### Community 58 - "record_transaction"
Cohesion: 0.07
Nodes (24): run(), run(), set_account_balance(), run(), _adjust_balance(), _ensure_can_cover(), get_account_balances(), get_or_create_account() (+16 more)

### Community 59 - "report"
Cohesion: 0.19
Nodes (12): run(), run(), balances(), default_query(), financial_snapshot(), first_entry_day(), insights(), load_rows() (+4 more)

### Community 60 - "package.json"
Cohesion: 0.11
Nodes (16): dependencies, @cloudflare/containers, description, devDependencies, wrangler, name, private, scripts (+8 more)

### Community 61 - "run"
Cohesion: 0.31
Nodes (3): DeliveryTests, FakeMessage, run()

### Community 62 - "firstrun.py"
Cohesion: 0.18
Nodes (8): truthy(), console_available(), ensure_setup(), setup_state(), SetupState, _values(), EnsureSetupTests, tmp_env()

### Community 63 - "Any"
Cohesion: 0.20
Nodes (11): cancel_pending(), classify_decision(), _config(), _interrupt_value(), Outcome, _outcome_from(), _pending_payload(), process_user_interaction_ex() (+3 more)

### Community 64 - "transaction_parser.py"
Cohesion: 0.16
Nodes (15): _bank_row_count(), _blank_dates(), _block_account(), _block_amount(), _clean_merchant(), _date_from_match(), _leading_date(), _money_tokens() (+7 more)

### Community 66 - "bot/main.py"
Cohesion: 0.16
Nodes (10): _drop_already_imported(), _finish_import(), _get_pending_import(), handle_document_rich(), _import_preview(), _merchant_match(), _parse_upload(), PendingImport (+2 more)

### Community 67 - "parse_receipt_text"
Cohesion: 0.17
Nodes (11): categorize_transaction(), _finalise_rows(), _guess_year(), _insights_for_session(), _learned_category(), _looks_like_person(), _normalize_line(), _numbered_lines() (+3 more)

### Community 68 - "seed"
Cohesion: 0.11
Nodes (6): EndToEndTests, PlanCommandTests, QuestionTests, run(), SavingsPlanTests, seed()

### Community 69 - "OnboardingTests"
Cohesion: 0.16
Nodes (7): ok_response(), OnboardingTests, ok(), run(), SetKeyFlowTests, ok(), ok()

### Community 70 - "_webhook"
Cohesion: 0.14
Nodes (10): _json_body(), simulate_chat(), SimulateMessageRequest, telegram_webhook(), telegram_webhook_for_bot(), _webhook(), bot_id(), feed_webhook_update() (+2 more)

### Community 71 - "WalletLedger project guide"
Cohesion: 0.11
Nodes (16): EncryptedText, Commands, Rules of the codebase, WalletLedger: notes for AI coding assistants, What it is, Workflow, 10. Tests and CI, 10b. The project map stays current by itself (+8 more)

### Community 72 - "AllKeysExhaustedError"
Cohesion: 0.12
Nodes (4): AIGatewayError, AllKeysExhaustedError, NoAPIKeyError, TestProviderTables

### Community 73 - "test_multi_bot.py"
Cohesion: 0.16
Nodes (9): webhook_url_for(), bot_tokens(), dev_endpoints_enabled(), go(), configure(), DeploymentFilesTests, MiniAppSecondBotTests, TokenListTests (+1 more)

### Community 74 - "5. The parts, one by one"
Cohesion: 0.10
Nodes (17): parse_amount(), parse_goal(), _plausible(), _to_amount(), Helpers that survive nlu.py, 5.10 Storage and encryption (`db.py`, `models.py`, `crypto.py`), 5.11 Setup, health, operations, 5.1 Rules (`nlu.py`) (+9 more)

### Community 75 - "inspect_statement.py"
Cohesion: 0.19
Nodes (6): _extract_pdf_text(), statement_text_from_file(), summarize_statement(), _cut(), main(), MerchantAndCategoryTests

### Community 76 - "budget_status"
Cohesion: 0.31
Nodes (4): run(), budget_status(), _day_start(), _now()

### Community 77 - "webhook_secret"
Cohesion: 0.21
Nodes (3): webhook_secret(), WebhookRouteTests, WebhookTests

### Community 78 - "decrypt_text"
Cohesion: 0.17
Nodes (7): decrypt_text(), decrypt_text_strict(), encrypt_text(), is_encrypted(), needs_rotation(), classify_field(), CryptoModuleTests

### Community 79 - "_parse_app_blocks"
Cohesion: 0.17
Nodes (8): _parse_app_blocks(), start(), track(), _parse_bhim(), _parse_gpay(), _parse_paytm(), _parse_phonepe(), StatementParse

### Community 80 - "extract_api_keys"
Cohesion: 0.14
Nodes (9): detect_provider(), extract_api_keys(), Agentic StateGraph (branch `feat/agentic-graph`), AgentState, Guardrails (`app/bot/guardrails.py`, no LLM calls), New tools (mcp_server + schema), Trade-offs, What stays deterministic (no LLM) (+1 more)

### Community 81 - "_parse_bank_table"
Cohesion: 0.29
Nodes (7): _delta_type(), _header_hits(), _is_bank_header(), _is_period(), _is_table_header(), _noise_reason(), _parse_bank_table()

### Community 82 - "main"
Cohesion: 0.20
Nodes (4): main(), NoConsole, DefaultsAndScriptTests, ask()

### Community 85 - "app.js"
Cohesion: 0.28
Nodes (5): copyText(), currentTheme(), legacyCopy(), SITE, syncThemeColor()

### Community 88 - "clock.py"
Cohesion: 0.22
Nodes (8): now_local(), now_utc(), to_local(), to_utc(), today_local(), tz(), _zone(), TimezoneTests

### Community 94 - ".check"
Cohesion: 0.20
Nodes (7): ValidationTests, fake(), busy(), behaviour(), limited(), bad(), busy()

### Community 95 - "validate_init_data"
Cohesion: 0.22
Nodes (5): InitData, webapp_auth(), validate_init_data(), MiniAppSignInTests, signed()

### Community 96 - "month_pace"
Cohesion: 0.25
Nodes (4): month_pace(), cumulative(), recurring(), RecurringTests

### Community 98 - "build_map.py"
Cohesion: 0.25
Nodes (8): build(), commands(), _first_line(), main(), markdown(), _module_name(), python_files(), read_python()

### Community 100 - "WalletLedger Architecture"
Cohesion: 0.15
Nodes (13): 10. Web dashboard and Mini App sign-in, 11. Button taps, 1. System overview, 2. One chat message, step by step, 3. The agent graph (LangGraph), 4. Tank & Pipes money model, 5. Data model, 6. Statement import (confirm before saving) (+5 more)

### Community 102 - "project.devprune.json"
Cohesion: 0.50
Nodes (3): prunable, directories, $schema

### Community 107 - "Data Storage and Security"
Cohesion: 0.15
Nodes (12): 1. What is stored where, 2. Authentication: how identity works, 3. Who can read what, 4. How the encryption works, 4b. "Can I read the encrypted data?" (a plain answer), 5. How to protect the rest of the data (recommended order), 6. Pre-deploy checklist, Changing SECRET_KEY (rotation) (+4 more)

### Community 109 - "WalletLedger project map"
Cohesion: 0.17
Nodes (12): AI: Talking to AI providers, tools the AI may call, Chat: Everything the user sees in Telegram, Commands, Data & safety: Database, encryption, health, Database tables (🔒 = encrypted column), Money: The numbers: ledger, analytics, charts, Scripts: Setup, demo data, maintenance, Site & deploy: Landing page, container, CI (+4 more)

### Community 110 - "build_docs.py"
Cohesion: 0.32
Nodes (6): build(), main(), nav_html(), page(), render_markdown(), rewrite_link()

### Community 112 - "canonical_category"
Cohesion: 0.22
Nodes (6): canonical_category(), _move_aliased_budgets(), set_category_budget(), run(), resolve_category(), Brain: Understands the message and decides what to do

### Community 113 - "best_model"
Cohesion: 0.22
Nodes (5): best_model(), clear_cache(), invalidate(), ListingTests, run()

### Community 115 - "On a server (always on)"
Cohesion: 0.18
Nodes (11): Before you let other people in, Cloudflare (tunnel or Containers), Dashboard link and Telegram Mini App, Deployment, Docker / serverless hosts, On a server (always on), On your own computer (simplest), PostgreSQL (+3 more)

### Community 116 - "Evaluating the AI agent"
Cohesion: 0.18
Nodes (10): AI tier: 13 / 16, Evaluating the AI agent, How a run works, Latest results in detail, Limits of this evaluation, Rules tier: 33 / 34, The dataset (ground truth), The short answer (+2 more)

### Community 118 - "io"
Cohesion: 0.24
Nodes (5): _fig(), _png(), render_chart(), render_dashboard(), _style()

### Community 119 - "rank_models"
Cohesion: 0.24
Nodes (5): _newest_all(), _pick_ollama(), rank_models(), _version_key(), RankingTests

### Community 120 - "How WalletLedger works, in plain words"
Cohesion: 0.20
Nodes (10): Charts, stats and the dashboard, Complex questions: one loop, four jobs, How WalletLedger works, in plain words, The idea, The money model: a tank with pipes, The pieces, in one line each, What happens when you send a message, Where the AI key comes in (+2 more)

### Community 121 - "model_chain"
Cohesion: 0.31
Nodes (6): _fingerprint(), forget_working(), list_models(), model_chain(), remember_working(), _working_model()

### Community 122 - "WalletLedger"
Cohesion: 0.22
Nodes (9): AI keys (bring your own), Cloudflare, For developers, License and contributors, Protect your data, Set it up (2 commands), Settings, WalletLedger (+1 more)

### Community 126 - "Running WalletLedger with Cloudflare"
Cohesion: 0.33
Nodes (6): Option A: Cloudflare Tunnel (recommended to start), Option B: Cloudflare Containers, Running WalletLedger with Cloudflare, Which should I use?, Why not plain Workers?, Your own tunnel (stable address)

### Community 128 - "Live demo script (about 8 minutes)"
Cohesion: 0.40
Nodes (5): Before you start (once, 5 minutes), If someone asks…, Live demo script (about 8 minutes), Reset after the demo, The story

### Community 129 - "Code map"
Cohesion: 0.40
Nodes (5): Adding a tool for the agent, Code map, Endpoints, Statement import, Tests

### Community 130 - "WalletLedger agent evaluation"
Cohesion: 0.40
Nodes (4): Files, Golden case format (one line of `golden.jsonl`), Safety rules of the runner, WalletLedger agent evaluation

### Community 131 - "WalletLedger agent eval: tier llm, mode direct"
Cohesion: 0.40
Nodes (4): Failed checks, Groups, Not run (budget), WalletLedger agent eval: tier llm, mode direct

### Community 135 - "WalletLedger agent eval: tier rules, mode direct"
Cohesion: 0.50
Nodes (3): Failed checks, Groups, WalletLedger agent eval: tier rules, mode direct

### Community 136 - "WalletLedger agent eval: tier rules, mode mcp"
Cohesion: 0.50
Nodes (3): Failed checks, Groups, WalletLedger agent eval: tier rules, mode mcp

### Community 137 - "WalletLedger agent eval: tier llm, mode direct"
Cohesion: 0.50
Nodes (3): Failed checks, Groups, WalletLedger agent eval: tier llm, mode direct

### Community 138 - "WalletLedger agent eval: tier llm, mode direct"
Cohesion: 0.50
Nodes (3): Failed checks, Groups, WalletLedger agent eval: tier llm, mode direct

### Community 139 - "WalletLedger agent eval: tier rules, mode direct"
Cohesion: 0.50
Nodes (3): Failed checks, Groups, WalletLedger agent eval: tier rules, mode direct

### Community 140 - "WalletLedger landing page"
Cohesion: 0.50
Nodes (3): How to edit, Publishing on GitHub Pages, WalletLedger landing page

## Knowledge Gaps
- **2 isolated node(s):** `wrangler`, `WalletLedger`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 780 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **32 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WalletLedger project guide` connect `WalletLedger project guide` to `mcp_server.py`, `README.md`, `5. The parts, one by one`, `8. Three walkthroughs`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 29 inferred relationships involving `FakeLLM` (e.g. with `TestAccountSelection` and `TestApiKeysInChat`) actually correct?**
  _`FakeLLM` has 29 INFERRED edges - model-reasoned connections that need verification._
- **What connects `wrangler`, `WalletLedger` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `init_db` be split into smaller, more focused modules?**
  _Cohesion score 0.06982456140350878 - nodes in this community are weakly interconnected._
- **Why does `handle_incoming()` connect `handle_incoming` to `mcp_server.py`, `.test_confirming_runs_every_call_from_that_message`, `tool`, `get_or_create_user`, `_engine.py`, `.add`, `execute_tool`, `.say`, `telegram.py`, `ConfirmationTests`, `test_import_logic.py`, `keys.py`, `handle_text`, `health.py`, `Any`, `AgentLoopTests`, `bot/main.py`, `seed`, `WalletLedger project guide`, `extract_api_keys`, `Evaluating the AI agent`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `record_transaction()` (e.g. with `4. How a message travels` and `5.5 Ledger (`ledger.py`)`) actually correct?**
  _`record_transaction()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `mcp_server.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0590990990990991 - nodes in this community are weakly interconnected._