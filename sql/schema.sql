-- WalletLedger schema (PostgreSQL 16+), generated from app/models.py.
-- Do not edit by hand: run `uv run python scripts/generate_schema.py` after model changes.
-- The app also creates missing tables on startup (init_db), so this file is for review,
-- manual setup (`psql -f sql/schema.sql`) and documentation.

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) NOT NULL,
    telegram_chat_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id);

CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(30) NOT NULL,
    balance FLOAT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS api_keys (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    encrypted_key TEXT NOT NULL,
    is_active BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS categories (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    budget_limit FLOAT,
    type VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS merchants (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    name VARCHAR(150) NOT NULL,
    default_category_id VARCHAR(36),
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(default_category_id) REFERENCES categories (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    merchant_id VARCHAR(36),
    name VARCHAR(100) NOT NULL,
    amount FLOAT NOT NULL,
    billing_cycle VARCHAR(20) NOT NULL,
    next_billing_date TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    account_id VARCHAR(36),
    to_account_id VARCHAR(36),
    category_id VARCHAR(36),
    merchant_id VARCHAR(36),
    amount FLOAT NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    description TEXT,
    source VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL,
    FOREIGN KEY(to_account_id) REFERENCES accounts (id) ON DELETE SET NULL,
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL,
    FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE SET NULL
);
