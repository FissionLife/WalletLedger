-- Payment API Seed Data
-- PostgreSQL 16+
-- Database: appdb

-- Clear existing data (optional - comment out if you want to preserve data)
TRUNCATE TABLE orders CASCADE;
TRUNCATE TABLE wallets CASCADE;
TRUNCATE TABLE users CASCADE;

-- Insert sample users
INSERT INTO users (user_id, email, full_name, phone, created_at, is_active) VALUES
('CUST-001', 'john.doe@example.com', 'John Doe', '+91-9876543210', CURRENT_TIMESTAMP, 'true'),
('CUST-002', 'jane.smith@example.com', 'Jane Smith', '+91-9876543211', CURRENT_TIMESTAMP, 'true'),
('CUST-003', 'bob.wilson@example.com', 'Bob Wilson', '+91-9876543212', CURRENT_TIMESTAMP, 'true'),
('CUST-004', 'alice.brown@example.com', 'Alice Brown', '+91-9876543213', CURRENT_TIMESTAMP, 'true'),
('CUST-005', 'charlie.davis@example.com', 'Charlie Davis', NULL, CURRENT_TIMESTAMP, 'true');

-- Insert wallets for users
INSERT INTO wallets (customer_id, balance, updated_at) VALUES
('CUST-001', 5000.00, CURRENT_TIMESTAMP),
('CUST-002', 3500.50, CURRENT_TIMESTAMP),
('CUST-003', 10000.00, CURRENT_TIMESTAMP),
('CUST-004', 750.25, CURRENT_TIMESTAMP),
('CUST-005', 0.00, CURRENT_TIMESTAMP);

-- Insert sample orders
INSERT INTO orders (id, customer_id, amount, currency, idempotency_key, status, created_at) VALUES
('550e8400-e29b-41d4-a716-446655440001', 'CUST-001', 499.99, 'INR', 'order-001-20240101', 'created', CURRENT_TIMESTAMP - INTERVAL '5 days'),
('550e8400-e29b-41d4-a716-446655440002', 'CUST-001', 299.50, 'INR', 'order-002-20240102', 'created', CURRENT_TIMESTAMP - INTERVAL '4 days'),
('550e8400-e29b-41d4-a716-446655440003', 'CUST-002', 1500.00, 'INR', 'order-003-20240103', 'created', CURRENT_TIMESTAMP - INTERVAL '3 days'),
('550e8400-e29b-41d4-a716-446655440004', 'CUST-002', 750.75, 'INR', 'order-004-20240104', 'created', CURRENT_TIMESTAMP - INTERVAL '2 days'),
('550e8400-e29b-41d4-a716-446655440005', 'CUST-003', 2500.00, 'INR', 'order-005-20240105', 'created', CURRENT_TIMESTAMP - INTERVAL '1 day'),
('550e8400-e29b-41d4-a716-446655440006', 'CUST-003', 350.25, 'INR', NULL, 'created', CURRENT_TIMESTAMP - INTERVAL '12 hours'),
('550e8400-e29b-41d4-a716-446655440007', 'CUST-004', 199.99, 'INR', 'order-007-20240107', 'created', CURRENT_TIMESTAMP - INTERVAL '6 hours'),
('550e8400-e29b-41d4-a716-446655440008', 'CUST-001', 899.00, 'INR', 'order-008-20240108', 'created', CURRENT_TIMESTAMP - INTERVAL '2 hours'),
('550e8400-e29b-41d4-a716-446655440009', 'CUST-002', 450.50, 'INR', NULL, 'created', CURRENT_TIMESTAMP - INTERVAL '1 hour'),
('550e8400-e29b-41d4-a716-446655440010', 'CUST-003', 1200.00, 'INR', 'order-010-20240110', 'created', CURRENT_TIMESTAMP);

-- Verify data insertion
SELECT 'Users inserted:' AS info, COUNT(*) AS count FROM users
UNION ALL
SELECT 'Wallets inserted:', COUNT(*) FROM wallets
UNION ALL
SELECT 'Orders inserted:', COUNT(*) FROM orders;

-- Display sample data
SELECT 'Sample Users:' AS info;
SELECT user_id, email, full_name, phone FROM users LIMIT 3;

SELECT 'Sample Wallets:' AS info;
SELECT customer_id, balance FROM wallets LIMIT 3;

SELECT 'Sample Orders:' AS info;
SELECT id, customer_id, amount, currency, status FROM orders LIMIT 3;
