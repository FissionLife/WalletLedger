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
    H -->|"/start /help /balance /report /setkey /keys"| CMD[Fixed commands]
    H -->|PDF / TXT| PARSE[transaction_parser]
    H -->|other text| AG[LangGraph agent<br/>app/bot/agent.py]

    AG --> MCP[Tool registry<br/>mcp_server.execute_tool]
    AG <-->|prompt + context| GW[AI Gateway<br/>LiteLLM]
    GW <--> LLM[(Gemini / OpenAI /<br/>Claude / Groq / Ollama)]
    GW --> KEYS[(api_keys<br/>Fernet-encrypted)]
    MCP --> LED[Ledger service]
    CMD --> LED
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
    B->>B: allow-list check, fixed commands
    B->>A: process_user_interaction(chat_id, text)
    A->>D: load last 20 chat messages, save redacted user message
    A->>G: reasoning prompt + history + tool schemas
    G-->>A: tool call log_expense(450, Food, Bank)
    alt large amount or ambiguous
        A-->>U: "Please confirm" (waits for yes / no)
    else
        A->>M: execute_tool(log_expense, ...)
        M->>L: record_transaction (validated)
        L->>D: one DB transaction: balance + transaction row
        L-->>M: new balance
        M-->>A: result
    end
    A->>G: synthesize friendly reply (persona)
    A->>D: save assistant message
    A-->>B: reply text
    B->>T: send_message
    T-->>U: "Expense logged ..."
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
    Q[ask_llm user_id, prompt] --> K{Keys available?<br/>user keys, then server env keys}
    K -- none --> NO[Error to caller<br/>agent shows offline-mode reply]
    K -- some --> RR[Start at next key round-robin]
    RR --> TRY[litellm call with that key]
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
