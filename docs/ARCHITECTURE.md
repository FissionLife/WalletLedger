# WalletLedger Architecture

GitHub, VS Code and most Markdown viewers render the Mermaid blocks below. For a guided tour of the
code with the file map, read the [project guide](PROJECT_GUIDE.md) first.

## 1. System overview

```mermaid
flowchart LR
    U([User on Telegram]) -->|message / PDF| TG[Telegram servers]
    TG -->|webhook POST + secret header| WH["/bot/webhook"]
    TG <-->|long polling| POLL[aiogram polling task]
    DEV([Developer]) -.->|only when dev endpoints enabled| SIM["/bot/simulate_chat"]

    WH --> TGM[app/bot/telegram.py<br/>aiogram dispatcher]
    POLL --> TGM
    TGM --> H["handle_text / handle_document<br/>(app/bot/main.py)"]
    SIM --> H

    H -->|allow-list check| H
    H -->|"/balance /stats /history /undo /budget /plan /dashboard /export"| VIEWS[Screens + charts<br/>views.py, analytics.py, charts.py]
    H -->|"/setkey /keys /admin"| KEYCMD[Key management<br/>keys.py]
    H -->|PDF / TXT| PARSE[transaction_parser]
    H -->|other text| AG[LangGraph agent<br/>app/bot/agent.py]
    AG -->|clear message| NLU[Rules: nlu.py<br/>no AI call]
    AG -->|goal or question| ORCH[Multi-step helper<br/>orchestrator.py]

    AG --> TC[tool_client.call_tool<br/>TOOL_MODE=direct or mcp]
    TC -->|direct: Python call| MCP[Tool registry<br/>mcp_server.TOOL_REGISTRY]
    TC -->|mcp: stdio JSON-RPC| MCPS[MCP server process<br/>mcp_transport]
    MCPS --> MCP
    ORCH --> TC
    AG <-->|prompt + context| GW[AI Gateway<br/>LiteLLM]
    ORCH <--> GW
    GW <--> LLM[(Gemini / OpenAI / Claude / Groq /<br/>OpenRouter / Grok / DeepSeek / Mistral / Ollama)]
    VIEWS --> LED
    VIEWS -.->|signed link| WEB[Web dashboard / Mini App<br/>app/web]
    WEB --> LED
    GW --> KEYS[(api_keys<br/>Fernet-encrypted)]
    KEYCMD -->|test live, then save| KEYS
    MCP --> LED[Ledger service]
    PARSE -->|user confirms import| LED
    AG --> HIST[(chat_messages<br/>history, keys redacted)]
    LED --> DB[(SQLite / Postgres)]
    KEYS --- DB
    HIST --- DB

    H -->|reply| TGM
    TGM --> TG
```

## 2. One chat message, step by step

```mermaid
sequenceDiagram
    actor U as User
    participant T as Telegram
    participant B as Bot (handle_text)
    participant A as LangGraph agent
    participant G as AI Gateway / LLM
    participant M as Tools (execute_tool)
    participant L as Ledger
    participant D as Database

    U->>T: "Spent 450 on dinner via Bank"
    T->>B: update (chat_id, text)
    B->>B: allow-list check, fixed commands (/stats, /plan, ...)
    B->>A: process_user_interaction(chat_id, text)
    A->>D: load last 20 chat messages, save redacted user message
    A->>A: rules (nlu.py) read the message: no AI needed
    Note over A,G: only if the rules cannot read it: ask the AI,<br/>or the multi-step helper for goals and questions
    alt transfer of 5,000 or more
        A-->>U: "Please confirm" [Yes] [Cancel]
    else
        A->>M: execute_tool(log_expense, ...)
        M->>L: record_transaction (validated)
        L->>D: one DB transaction: balance + transaction row
        L-->>M: new balance
        M-->>A: result
    end
    A->>D: save assistant message
    A-->>B: reply text + transaction ids
    B->>T: send_message with [Undo] button
    T-->>U: "-450 Food & Dining / Bank 84,550"
```

## 3. The agent graph (LangGraph)

```mermaid
flowchart TD
    S([START]) --> R[llm_reasoning<br/>understand message, pick tool]
    R -->|is a yes/no reply| C[confirmation_node]
    R -->|tool chosen or needs confirmation| T[tool_executor]
    R -->|plain conversation| Y[response_synthesizer]
    C -->|confirmed| T
    C -->|declined / unclear| Y
    T --> Y
    Y --> E([END: reply text])
```

### The multi-step helper (goals and questions)

For "can I afford ...", "how am I doing", "I want to save ...", the AI runs a short loop instead of
a single call. Same tools as everywhere, a few extra guard rails.

```mermaid
flowchart TD
    Q[Question or goal<br/>no clear transaction in it] --> L1[AI chooses tools]
    L1 -->|no tools needed| ANS[Final short answer]
    L1 -->|tool calls| CHK{Allowed?}
    CHK -->|"save_user_api_key / unknown tool"| SKIP[Refused, AI is told]
    CHK -->|"transfer of 5,000 or more"| WAIT[Stop and ask the user: Yes / Cancel]
    CHK -->|ok| RUN[Run tool for THIS user<br/>user_id is always overwritten]
    SKIP --> L2[AI reads the results]
    RUN --> L2
    L2 -->|"max 5 rounds, 12 tool calls"| L1
    L2 --> ANS
    L1 -.->|AI unavailable and nothing changed yet| FB[Fall back to the simple single-call path]
```

The roles (Ledger records, Analyst looks at real numbers, Planner uses `savings_plan`, Writer answers
briefly) are instructions in one prompt, not separate programs.

## 4. Tank & Pipes money model

```mermaid
flowchart LR
    SAL[Salary / income] -->|income| BANK[(Bank)]
    FREE[Freelance] -->|income| WAL[(Wallet)]
    BANK -->|transfer: NOT an expense| CASH[(Cash)]
    BANK -->|expense| FOOD[Food & Dining]
    CASH -->|expense| TRANS[Transport]
    CC[(Credit Card)] -->|expense| SHOP[Shopping]
    subgraph TANK["Tank = sum of all account balances"]
      BANK
      CASH
      WAL
      CC
    end
```

Expense: balance goes down and a category is charged. Income: balance goes up. Transfer: one
account down, another up, nothing counted as spending.

## 5. Data model

```mermaid
erDiagram
    USERS ||--o{ ACCOUNTS : owns
    USERS ||--o{ CATEGORIES : owns
    USERS ||--o{ MERCHANTS : owns
    USERS ||--o{ TRANSACTIONS : owns
    USERS ||--o{ API_KEYS : owns
    USERS ||--o{ CHAT_MESSAGES : has
    USERS ||--o{ SUBSCRIPTIONS : owns
    ACCOUNTS ||--o{ TRANSACTIONS : "source (account_id)"
    ACCOUNTS ||--o{ TRANSACTIONS : "destination (to_account_id)"
    CATEGORIES ||--o{ TRANSACTIONS : classifies
    MERCHANTS ||--o{ TRANSACTIONS : "paid to"
    USERS { string id PK
            string telegram_chat_id UK }
    ACCOUNTS { string name
               string type
               float balance }
    TRANSACTIONS { float amount
                   string transaction_type
                   string source
                   datetime created_at
                   text description "ENCRYPTED" }
    API_KEYS { string provider
               text encrypted_key "ENCRYPTED (vault key)"
               bool is_active }
    CHAT_MESSAGES { string role
                    text content "ENCRYPTED" }
```

Columns marked ENCRYPTED hold `enc1:...` ciphertext in the file (section 9). Everything else is
readable by the database so it can add up, filter and group.

## 6. Statement import (confirm before saving)

```mermaid
flowchart TD
    A[User sends PDF / TXT] --> B{type and size OK?}
    B -- no --> X[Reject with message]
    B -- yes --> C[Download via Bot API]
    C --> D[Extract text and parse rows<br/>PDF via PyPDF2]
    D --> D2[Detect format: PhonePe, GPay, Paytm, BHIM,<br/>bank table or SMS. Keep the statement's own dates]
    D2 --> E[Preview: N rows, date range, totals, top categories]
    E --> F{User taps Import / Cancel}
    F -- no --> X2[Discard]
    F -- yes --> DD[Skip rows already in the ledger<br/>same type, amount, date and note]
    DD --> G[record_transaction per row, source=pdf, dated as in the statement]
    G --> H[Reply: imported count]
```

## 7. LLM key rotation and fallback

```mermaid
flowchart TD
    Q[ask_llm user_id, prompt] --> K{Keys available?<br/>1 the user's own, 2 shared keys the admin added, 3 server .env keys}
    K -- none --> NO[Error to caller<br/>agent shows offline-mode reply]
    K -- some --> RR[Start at next key round-robin]
    RR --> TRY[litellm call with that key<br/>best model for that key, discovered automatically]
    TRY -- "model retired or busy" --> TRY2[Next model on the SAME key]
    TRY2 --> TRY
    TRY -- success --> OK[Return text]
    TRY -- "429 / quota / auth / outage" --> CD[Cool down that key]
    CD --> NEXT{More keys?}
    NEXT -- yes --> TRY
    NEXT -- no --> NO
```

## 8. Deployment modes

```mermaid
flowchart LR
    subgraph Local["Local dev"]
      L1[uvicorn] --- L2[(SQLite file)]
      L1 -.->|long polling| TGL[Telegram]
      L3[curl] -->|simulate_chat| L1
    end
    subgraph Prod["Production"]
      TGP[Telegram] -->|HTTPS webhook + secret| RP[Reverse proxy / TLS]
      RP --> P1[uvicorn]
      P1 --> PG[(Postgres via docker-compose<br/>or managed, TLS)]
      ENV[(Secrets from env / vault:<br/>BOT TOKEN, SECRET_KEY, webhook secret)] --> P1
    end
```

## 9. Data at rest and encryption

```mermaid
flowchart LR
    S[SECRET_KEY<br/>from .env] --> H1[HKDF-SHA256<br/>label: field/v1]
    S --> H2[HKDF-SHA256<br/>label: api-key-vault/v1]
    H1 --> F1[Fernet<br/>AES-128-CBC + HMAC, random IV]
    H2 --> F2[Fernet]
    APP[App code<br/>sees plain text] <-->|EncryptedText column type| F1
    APP <-->|encrypt_vault / decrypt_vault| F2
    F1 --> D1[(transactions.description<br/>chat_messages.content<br/>stored as enc1:gAAAA...)]
    F2 --> D2[(api_keys.encrypted_key<br/>stored as gAAAA...)]
    D1 --- FILE[(walletledger.db / Postgres)]
    D2 --- FILE
    PLAIN[amounts, dates, accounts, categories,<br/>merchants, chat id: plain columns] --- FILE
```

Whoever has the file **and** `SECRET_KEY` can read everything; the file alone shows only ciphertext
and the plain columns. Rotation: put the old secret in `SECRET_KEY_OLD`, run
`scripts/protect_data.py rotate`. Full explanation: [SECURITY.md](SECURITY.md).

## 10. Web dashboard and Mini App sign-in

```mermaid
sequenceDiagram
    actor U as User
    participant B as Bot (/dashboard)
    participant W as Browser or Telegram Mini App
    participant S as Server (app/web)
    participant A as analytics.report
    U->>B: /dashboard
    B->>B: token = base64(chat id, expiry) + HMAC(SECRET_KEY-derived key)
    B-->>U: PUBLIC_URL/d/token (button opens the Mini App if https)
    U->>W: open link
    W->>S: GET /d/token  (page only, no data)
    S-->>W: dashboard.html + js + css
    W->>S: GET /api/dashboard?period=90d  (token in a header)
    S->>S: verify signature, expiry, rate limit
    S->>A: report(chat id, Query)
    A-->>S: one dictionary of numbers
    S-->>W: JSON, no-store, strict CSP
    W->>W: draw 12 SVG charts, filters, table
    Note over W,S: In Telegram the sign-in is instead Telegram's signed initData, verified by /api/webapp/auth
```

## 11. Button taps

```mermaid
flowchart LR
    TAP[User taps a button<br/>callback data e.g. st:30d, ch:trend:90d, undo:ab12, ask:yes] --> CB[telegram.on_callback]
    CB --> HC[callbacks.handle_callback<br/>allow-list check, parse action]
    HC -->|go / st / ch / hi / ex| VW[views.* screens]
    HC -->|undo| LD[ledger.undo_transaction]
    HC -->|ask / imp| PEND[pending confirmation<br/>agent or statement import]
    HC -->|key| KM[keys.py]
    VW --> RP[Reply: text, image, buttons]
    LD --> RP
    PEND --> RP
    KM --> RP
    RP --> ED[edit the existing message<br/>instead of sending a new one]
```

The same map, clickable and generated from the code, is the [explorer](https://fissionlife.github.io/WalletLedger/explore/). Where each box lives in the code, with the reasons behind it, is in the
[project guide](PROJECT_GUIDE.md).
