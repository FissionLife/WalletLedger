# WalletLedger Architecture

GitHub, VS Code and most Markdown viewers render the Mermaid blocks below.

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

    AG --> MCP[Tool registry<br/>mcp_server.execute_tool]
    ORCH --> MCP
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
                   datetime created_at }
    API_KEYS { string provider
               text encrypted_key
               bool is_active }
    CHAT_MESSAGES { string role
                    text content }
```

## 6. Statement import (confirm before saving)

```mermaid
flowchart TD
    A[User sends PDF / TXT] --> B{type and size OK?}
    B -- no --> X[Reject with message]
    B -- yes --> C[Download via Bot API]
    C --> D[Extract text and parse rows<br/>PDF via PyPDF2]
    D --> E[Preview: N rows found]
    E --> F{User replies yes / no}
    F -- no --> X2[Discard]
    F -- yes --> G[record_transaction per row, source=pdf]
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
