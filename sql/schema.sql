-- Payment API Database Schema
-- PostgreSQL 16+
-- Database: appdb

-- Drop tables if they exist (for clean setup)
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS wallets CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Create users table
CREATE TABLE users (
    user_id VARCHAR(100) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active VARCHAR(10) DEFAULT 'true'
);

-- Create index on email for faster lookups
CREATE INDEX idx_users_email ON users(email);

-- Create index on created_at for sorting
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- Create wallets table
CREATE TABLE wallets (
    customer_id VARCHAR(100) PRIMARY KEY,
    balance NUMERIC(10, 2) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_wallet_user FOREIGN KEY (customer_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT check_wallet_balance_non_negative CHECK (balance >= 0)
);

-- Create index on updated_at
CREATE INDEX idx_wallets_updated_at ON wallets(updated_at DESC);

-- Create orders table
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    idempotency_key TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_order_user FOREIGN KEY (customer_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT check_order_amount_positive CHECK (amount > 0)
);

-- Create indexes for orders
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_idempotency_key ON orders(idempotency_key);

-- Add comments for documentation
COMMENT ON TABLE users IS 'Stores customer/user information';
COMMENT ON TABLE wallets IS 'Stores customer wallet balances';
COMMENT ON TABLE orders IS 'Stores customer orders with idempotency support';

COMMENT ON COLUMN users.user_id IS 'Unique user identifier (e.g., CUST-001)';
COMMENT ON COLUMN users.email IS 'User email address (unique)';
COMMENT ON COLUMN users.full_name IS 'User full name';
COMMENT ON COLUMN users.phone IS 'User phone number (optional)';
COMMENT ON COLUMN users.is_active IS 'User account status (true/false)';

COMMENT ON COLUMN wallets.customer_id IS 'References users.user_id';
COMMENT ON COLUMN wallets.balance IS 'Current wallet balance (must be >= 0)';

COMMENT ON COLUMN orders.id IS 'Unique order identifier (UUID)';
COMMENT ON COLUMN orders.customer_id IS 'References users.user_id';
COMMENT ON COLUMN orders.amount IS 'Order amount (must be > 0)';
COMMENT ON COLUMN orders.currency IS 'Currency code (e.g., INR, USD)';
COMMENT ON COLUMN orders.idempotency_key IS 'Client-provided idempotency key for duplicate prevention';
COMMENT ON COLUMN orders.status IS 'Order status (e.g., created, completed, failed)';
