# Payment API - Technical Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Database Schema](#database-schema)
4. [API Flows](#api-flows)
5. [Local Deployment Guide](#local-deployment-guide)
6. [Testing Guide](#testing-guide)
7. [Development Guidelines](#development-guidelines)

---

## Project Overview

The Payment API is a FastAPI-based backend service that provides order management and wallet functionality for payment processing. It's designed as a production-ready system with proper separation of concerns, database persistence, and RESTful API design.

### Tech Stack
- **Framework**: FastAPI 0.109.0
- **Database**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.0.25
- **Validation**: Pydantic v2
- **Server**: Uvicorn
- **Python**: 3.11+

### Key Features
- User management with email validation
- Order creation with idempotency key support
- Customer wallet management (credit/debit operations)
- Foreign key relationships ensuring data integrity
- RESTful API design
- Automatic database schema initialization
- Request/response validation with Pydantic v2
- Extensible authentication framework

---

## Architecture

### Project Structure

```
payment-api/
├── app/
│   ├── __init__.py
│   ├── main.py           # Application entry point, router registration
│   ├── config.py         # Environment configuration
│   ├── db.py             # Database connection and session management
│   ├── models.py         # SQLAlchemy ORM models (User, Order, Wallet)
│   ├── schemas.py        # Pydantic request/response models with validation
│   ├── services.py       # Business logic layer
│   ├── routes_users.py   # User endpoints
│   ├── routes_orders.py  # Order endpoints
│   ├── routes_wallet.py  # Wallet endpoints
│   └── auth.py           # Authentication framework (extensible)
├── scripts/
│   ├── run_scenarios.py  # API testing scenarios
│   └── seed_data.py      # Database seeding utility
├── sql/
│   ├── schema.sql        # Database schema definition
│   └── seed_data.sql     # Sample data for testing
├── requirements.txt
├── .gitignore
├── README.md
├── DEPLOYMENT.md
└── DOCUMENTATION.md
```

### Layered Architecture

```
┌──────────────────────────────────────────────────┐
│              API Layer (Routes)                  │
│  routes_users.py, routes_orders.py,              │
│  routes_wallet.py                                │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│         Business Logic (Services)                │
│  User CRUD, Order Management, Wallet Operations  │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│         Data Access Layer (ORM)                  │
│  User, Order, Wallet models with relationships   │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│            PostgreSQL Database                   │
│  users, orders, wallets tables with FK           │
└──────────────────────────────────────────────────┘
```

### Component Responsibilities

**main.py**
- FastAPI application initialization
- Router registration
- Startup event handlers (database initialization)
- Health check endpoints

**config.py**
- Environment variable management
- Database connection string configuration
- Settings using Pydantic BaseSettings

**db.py**
- SQLAlchemy engine creation
- Session factory
- Database initialization
- Session dependency for dependency injection

**models.py**
- SQLAlchemy ORM models (User, Order, Wallet)
- Database constraints and foreign key relationships
- Table definitions with relationships

**schemas.py**
- Pydantic models for request validation with constraints
- Response serialization models
- Data transfer objects (DTOs)
- Email validation, pattern matching, field limits

**services.py**
- Business logic implementation
- User CRUD operations
- Order and wallet management
- Transaction management
- Data validation and processing

**routes_*.py**
- HTTP endpoint definitions
- Request/response handling
- Dependency injection
- Error handling

**auth.py**
- Authentication framework skeleton
- Extensible for JWT or other auth mechanisms
- User model definition

---

## Database Schema

### Tables

#### `users`
Stores customer/user information.

| Column       | Type         | Constraints                    | Description                          |
|--------------|--------------|--------------------------------|--------------------------------------|
| user_id      | VARCHAR(100) | PRIMARY KEY                    | Unique user identifier (e.g., CUST-001) |
| email        | VARCHAR(255) | UNIQUE, NOT NULL               | User email address                   |
| full_name    | VARCHAR(255) | NOT NULL                       | User full name                       |
| phone        | VARCHAR(20)  | NULLABLE                       | User phone number (optional)         |
| created_at   | TIMESTAMP    | DEFAULT NOW()                  | Account creation timestamp           |
| is_active    | VARCHAR(10)  | DEFAULT 'true'                 | Account status (true/false)          |

**Indexes**: 
- Primary key on `user_id`
- Index on `email`
- Index on `created_at`

**Constraints**:
- Unique constraint on `email`

#### `orders`
Stores customer orders with idempotency support.

| Column           | Type         | Constraints                    | Description                          |
|------------------|--------------|--------------------------------|--------------------------------------|
| id               | UUID         | PRIMARY KEY                    | Unique order identifier              |
| customer_id      | VARCHAR(100) | NOT NULL, FK → users.user_id   | Customer identifier                  |
| amount           | NUMERIC(10,2)| NOT NULL, CHECK (amount > 0)   | Order amount                         |
| currency         | VARCHAR(10)  | NOT NULL                       | Currency code (e.g., INR, USD)       |
| idempotency_key  | TEXT         | NULLABLE                       | Client-provided idempotency key      |
| status           | VARCHAR(50)  | NOT NULL, DEFAULT 'created'    | Order status                         |
| created_at       | TIMESTAMP    | DEFAULT NOW()                  | Order creation timestamp             |

**Indexes**: 
- Primary key on `id`
- Index on `customer_id`
- Index on `created_at`
- Index on `status`
- Index on `idempotency_key`

**Constraints**:
- `check_order_amount_positive`: Ensures amount > 0
- Foreign key: `customer_id` → `users.user_id` (CASCADE DELETE)

#### `wallets`
Stores customer wallet balances.

| Column       | Type         | Constraints                        | Description                     |
|--------------|--------------|------------------------------------|---------------------------------|
| customer_id  | VARCHAR(100) | PRIMARY KEY, FK → users.user_id    | Customer identifier             |
| balance      | NUMERIC(10,2)| NOT NULL, DEFAULT 0, CHECK >= 0    | Current wallet balance          |
| updated_at   | TIMESTAMP    | DEFAULT NOW(), ON UPDATE NOW()     | Last update timestamp           |

**Indexes**: 
- Primary key on `customer_id`
- Index on `updated_at`

**Constraints**:
- `check_wallet_balance_non_negative`: Ensures balance >= 0
- Foreign key: `customer_id` → `users.user_id` (CASCADE DELETE)

### Entity Relationships

```
┌──────────────────┐
│      users       │
│  (user_id PK)    │
│  - email         │
│  - full_name     │
│  - phone         │
└────────┬─────────┘
         │
         ├─────────────────────┐
         │                     │
         ▼                     ▼
┌────────────────┐    ┌────────────────┐
│    orders      │    │    wallets     │
│  (id PK)       │    │ (customer_id PK)│
│  - customer_id │    │  - balance     │
│  - amount      │    │  - updated_at  │
│  - currency    │    └────────────────┘
│  - status      │
│  FK → users    │
└────────────────┘

Relationships:
- User → Orders: One-to-Many
- User → Wallet: One-to-One
- CASCADE DELETE: Deleting a user removes their orders and wallet
```

---

## API Flows

### 1. User Creation Flow

```
Client Request
     │
     ▼
POST /users
     │
     ▼
┌────────────────────────────────┐
│  Validate Request (Pydantic)   │
│  - user_id pattern (CUST-001)  │
│  - email format validation     │
│  - full_name required          │
│  - phone optional              │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.create_user()        │
│  - Check user_id uniqueness    │
│  - Check email uniqueness      │
│  - Create User object          │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Database Transaction          │
│  - INSERT into users table     │
│  - COMMIT                      │
└────────────┬───────────────────┘
             │
             ▼
     Return Response
  { user_id, email, full_name, ... }
```

**Request Example**:
```json
POST /users
{
  "user_id": "CUST-001",
  "email": "customer@example.com",
  "full_name": "John Doe",
  "phone": "+91-9876543210"
}
```

**Response Example**:
```json
{
  "user_id": "CUST-001",
  "email": "customer@example.com",
  "full_name": "John Doe",
  "phone": "+91-9876543210",
  "created_at": "2024-01-15T10:30:00",
  "is_active": "true"
}
```

### 2. Order Creation Flow

```
Client Request
     │
     ▼
POST /orders
     │
     ▼
┌────────────────────────────────┐
│  Validate Request (Pydantic)   │
│  - customer_id required        │
│  - amount > 0                  │
│  - currency format             │
│  - optional idempotency_key    │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.create_order()       │
│  - Generate UUID               │
│  - Create Order object         │
│  - Set status = 'created'      │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Database Transaction          │
│  - INSERT into orders table    │
│  - COMMIT                      │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Processing Delay              │
│  (Simulates payment gateway)   │
└────────────┬───────────────────┘
             │
             ▼
     Return Response
  { order_id, status }
```

**Request Example**:
```json
POST /orders
{
  "customer_id": "CUST-001",
  "amount": 499.99,
  "currency": "INR",
  "idempotency_key": "order-abc-123"
}
```

**Response Example**:
```json
{
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "created"
}
```

### 3. Wallet Credit Flow

```
Client Request
     │
     ▼
POST /wallet/{customer_id}/credit
     │
     ▼
┌────────────────────────────────┐
│  Validate Request              │
│  - amount > 0                  │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.get_wallet()         │
│  - Query wallet by customer_id │
│  - Create if not exists        │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.credit_wallet()      │
│  - Read current balance        │
│  - Calculate new balance       │
│  - Update wallet.balance       │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Database Transaction          │
│  - UPDATE wallets              │
│  - COMMIT                      │
└────────────┬───────────────────┘
             │
             ▼
     Return Response
  { customer_id, balance }
```

**Request Example**:
```json
POST /wallet/CUST-001/credit
{
  "amount": 1000.00
}
```

**Response Example**:
```json
{
  "customer_id": "CUST-001",
  "balance": 1000.00
}
```

### 4. Wallet Debit Flow

```
Client Request
     │
     ▼
POST /wallet/{customer_id}/debit
     │
     ▼
┌────────────────────────────────┐
│  Validate Request              │
│  - amount > 0                  │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.get_wallet()         │
│  - Query wallet by customer_id │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  services.debit_wallet()       │
│  - Read current balance        │
│  - Check sufficient funds      │
│  - Calculate new balance       │
│  - Update wallet.balance       │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Database Transaction          │
│  - UPDATE wallets              │
│  - COMMIT                      │
└────────────┬───────────────────┘
             │
             ▼
     Return Response
  { customer_id, balance }
```

**Error Handling**: Returns 400 Bad Request if insufficient balance.

### 5. Query Orders Flow

```
Client Request
     │
     ▼
GET /orders?customer_id=CUST-001
     │
     ▼
┌────────────────────────────────┐
│  services.get_orders_by_       │
│  customer()                    │
│  - Query orders table          │
│  - Filter by customer_id       │
└────────────┬───────────────────┘
             │
             ▼
     Return List of Orders
```

**Response Example**:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "customer_id": "CUST-001",
    "amount": 499.99,
    "currency": "INR",
    "status": "created",
    "created_at": "2024-01-15T10:30:00"
  }
]
```

---

## Local Deployment Guide

### Prerequisites

Ensure you have the following installed:
- **Python 3.11 or higher**
- **Docker** (for PostgreSQL)
- **pip** (Python package manager)
- **Git** (for cloning the repository)

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd payment-api
```

### Step 2: Set Up PostgreSQL Database

Start a PostgreSQL container using Docker:

```bash
docker run --name app_pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=appdb \
  -p 5432:5432 \
  -d postgres:16
```

**Verify PostgreSQL is running**:
```bash
docker ps | grep app_pg
```

**Check PostgreSQL logs** (if needed):
```bash
docker logs app_pg
```

**Stop PostgreSQL** (when needed):
```bash
docker stop app_pg
```

**Start PostgreSQL** (after stopping):
```bash
docker start app_pg
```

**Remove PostgreSQL container** (to start fresh):
```bash
docker stop app_pg
docker rm app_pg
```

### Step 3: Create Python Virtual Environment

```bash
python3.11 -m venv .venv
```

**Activate the virtual environment**:

On macOS/Linux:
```bash
source .venv/bin/activate
```

On Windows:
```bash
.venv\Scripts\activate
```

### Step 4: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Verify installation**:
```bash
pip list
```

You should see:
- fastapi
- uvicorn
- sqlalchemy
- psycopg2-binary
- pydantic
- pydantic-settings
- requests

### Step 5: Configure Environment (Optional)

The application uses default configuration, but you can override it by creating a `.env` file:

```bash
# .env file (optional)
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/appdb
```

### Step 6: Run the Application

```bash
uvicorn app.main:app --reload --port 8000
```

**Expected output**:
```
INFO:     Will watch for changes in these directories: ['/path/to/payment-api']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReload
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 7: Verify Installation

**Check health endpoint**:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy"}
```

**Check API documentation**:
Open your browser and navigate to:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Step 8: Seed Initial Data (Optional)

```bash
python scripts/seed_data.py CUST-001
```

This will:
- Create a wallet for CUST-001 with 1000 INR balance
- Create 3 sample orders

---

## Testing Guide

### Manual Testing with cURL

**Create an order**:
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "amount": 499.99,
    "currency": "INR",
    "idempotency_key": "test-order-1"
  }'
```

**List orders**:
```bash
curl "http://localhost:8000/orders?customer_id=CUST-001"
```

**Credit wallet**:
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/credit \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000}'
```

**Debit wallet**:
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/debit \
  -H "Content-Type: application/json" \
  -d '{"amount": 200}'
```

**Get wallet balance**:
```bash
curl http://localhost:8000/wallet/CUST-001
```

