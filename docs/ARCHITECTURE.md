# WalletLedger Architecture

GitHub, VS Code and most Markdown viewers render the Mermaid blocks below.

## 1. System overview

```mermaid
flowchart LR
    U([User on Telegram]) -->|message / PDF| TG[Telegram servers]
    TG -->|webhook POST + secret header| WH["/bot/webhook"]
    TG <-->|long polling getUpdates| POLL[Polling loop]
    DEV([Developer]) -.->|only if ENABLE_DEV_ENDPOINTS| SIM["/bot/simulate_chat"]

    WH --> H[handle_incoming]
    POLL --> H
    SIM --> H

    H -->|allow-list check| H
    H -->|/start /help| STATIC[Static replies]
    H -->|document| DOC[PDF / TXT parser]
    H -->|text| AG[LangGraph agent]

    AG --> MCP[Tool registry<br/>execute_tool]
    AG <-->|only if user has a key| GW[AI Gateway<br/>LiteLLM]
    GW <-->|financial context + prompt| LLM[(Gemini / OpenAI /<br/>Groq / Claude)]
    DOC --> LED
    MCP --> LED[Ledger service]
    MCP --> INS[Insights + skills]
    INS --> LED
    GW --> KEYS[(api_keys<br/>Fernet-encrypted)]
    LED --> DB[(SQLite / Postgres)]
    KEYS --- DB

    H -->|reply| BOT[aiogram send_message]
    BOT --> TG
```

## 2. One chat message, step by step

```mermaid
sequenceDiagram
    actor U as User
    participant T as Telegram
    participant B as Bot (handle_incoming)
    participant A as LangGraph agent
    participant M as Tools (execute_tool)
    participant L as Ledger
    participant D as Database
    participant G as AI Gateway / LLM

    U->>T: "Spent 450 on dinner via Bank"
    T->>B: update (chat_id, text)
    B->>B: verify secret header, allow-list
    B->>A: process_user_interaction(chat_id, text)
    A->>A: pending "yes/no" confirmation? mode switch?
    A->>D: get_or_create_user(chat_id)
    A->>A: classify (regex rules)
    opt rules found nothing AND user has an API key
        A->>G: intent-classifier prompt
        G-->>A: JSON intent
    end
    A->>M: log_expense(user_id, 450, Food & Dining, Bank)
    M->>L: record_transaction
    L->>D: one DB transaction: account balance + transaction row
    L-->>M: new balance
    M-->>A: result dict
    A-->>B: formatted reply
    B->>T: send_message
    T-->>U: "Expense logged ..."
```

## 3. The agent graph (LangGraph)

```mermaid
flowchart TD
    S([START]) --> PRE{Pending large-amount<br/>confirmation?}
    PRE -- "yes / no" --> EXEC[Run or cancel stored action] --> E
    PRE -- no --> MODE{"'ruthless mode' etc.?"}
    MODE -- yes --> SW[Switch persona] --> E
    MODE -- no --> C[classify node]
    C --> ACT[act node]
    ACT --> I{intent}
    I -->|expense / income / transfer| T1{amount >= threshold?}
    T1 -- yes --> ASK[Store pending, ask 'yes?']
    T1 -- no --> TOOL[Run ledger tool]
    I -->|balance / report| Q[Query tools]
    I -->|advice| ADV[insights + recurring bills + budget alerts]
    I -->|set_key| KEY[Encrypt + store API key]
    I -->|other| OTH[LLM chat if key, else help text]
    ASK --> R
    TOOL --> R
    Q --> R
    ADV --> R
    KEY --> R
    OTH --> R[respond node<br/>template or LLM wording]
    R --> E([END: reply text])
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

Expense: balance goes down, a category is charged. Income: balance goes up. Transfer: one account
down, another up, nothing is counted as spending.

## 5. Data model

```mermaid
erDiagram
    USERS ||--o{ ACCOUNTS : owns
    USERS ||--o{ CATEGORIES : owns
    USERS ||--o{ MERCHANTS : owns
    USERS ||--o{ TRANSACTIONS : owns
    USERS ||--o{ API_KEYS : owns
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
```

## 6. PDF statement import

```mermaid
flowchart TD
    A[User sends PDF / TXT in Telegram] --> B{size <= 10 MB and .pdf/.txt?}
    B -- no --> X[Reject with message]
    B -- yes --> C[Download via Bot API]
    C --> D{starts with %PDF, not encrypted?}
    D -- no --> X
    D -- yes --> E[PyPDF2 text extraction, max 200 pages]
    E --> F[Split into blocks at each date line]
    F --> G[Find amount, DEBIT/CREDIT, payee, auto-categorise]
    G --> H[Skip rows already imported<br/>same date + amount + payee]
    H --> I[record_transaction for each new row, source=pdf]
    I --> J[Reply: N imported, M duplicates]
```

## 7. LLM key rotation and fallback

```mermaid
flowchart TD
    Q[ask_llm user_id, prompt] --> K{Active keys for user<br/>+ optional server key?}
    K -- none --> NO[LLMUnavailable<br/>agent falls back to templates]
    K -- some --> RR[Pick start index = round-robin counter]
    RR --> TRY[litellm.acompletion with that key, 45s timeout]
    TRY -- success --> OK[Return text]
    TRY -- "429 / quota / error" --> NEXT{More keys?}
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
      P1 --> PG[(Postgres, encrypted disk, TLS)]
      ENV[(Secrets from env / vault:<br/>BOT TOKEN, SECRET_KEY, WEBHOOK_SECRET)] --> P1
    end
```
