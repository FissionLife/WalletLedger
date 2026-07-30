# Payment API

A FastAPI-based payment processing system with user management, order processing, and wallet functionality.

## Quick Links

- 📖 [Complete Deployment Guide](DEPLOYMENT.md) - Step-by-step local setup instructions
- 📚 [Technical Documentation](DOCUMENTATION.md) - Architecture, flows, and development guide
- 🔗 [API Documentation](http://localhost:8000/docs) - Interactive Swagger UI (after starting server)

## Prerequisites

- Python 3.11+
- Docker
- PostgreSQL (via Docker)

## Quick Start

### 1. Start PostgreSQL

```bash
docker run --name app_pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=appdb -p 5432:5432 -d postgres:16
```

### 2. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the Application

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

### 4. Seed Sample Data

```bash
# Seed multiple users with wallets and orders
python scripts/seed_data.py --all

# Or seed a single user
python scripts/seed_data.py CUST-001
```

## API Endpoints

### Users

**Create User**
```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "CUST-001",
    "email": "customer@example.com",
    "full_name": "John Doe",
    "phone": "+91-9876543210"
  }'
```

**Get User**
```bash
curl http://localhost:8000/users/CUST-001
```

**List Users**
```bash
curl http://localhost:8000/users
```

### Orders

**Create Order**
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "amount": 499.99,
    "currency": "INR",
    "idempotency_key": "order-123"
  }'
```

**List Orders**
```bash
curl "http://localhost:8000/orders?customer_id=CUST-001"
```

### Wallet

**Credit Wallet**
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/credit \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000}'
```

**Debit Wallet**
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/debit \
  -H "Content-Type: application/json" \
  -d '{"amount": 200}'
```

**Get Wallet Balance**
```bash
curl http://localhost:8000/wallet/CUST-001
```

## Testing Scenarios

Run various test scenarios to validate the API:

```bash
# Run all scenarios with seeding
python scripts/run_scenarios.py --scenario all --seed

# Run specific scenario
python scripts/run_scenarios.py --scenario orders_retry
python scripts/run_scenarios.py --scenario wallet_concurrency
python scripts/run_scenarios.py --scenario false_success

# Repeat scenario multiple times
python scripts/run_scenarios.py --scenario wallet_concurrency --repeat 5
```

## Database Management

### Using SQL Files

**Initialize schema:**
```bash
docker exec -i app_pg psql -U postgres -d appdb < sql/schema.sql
```

**Load seed data:**
```bash
docker exec -i app_pg psql -U postgres -d appdb < sql/seed_data.sql
```

**Connect to database:**
```bash
docker exec -it app_pg psql -U postgres -d appdb
```

## Project Structure

```
payment-api/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI application
│   ├── config.py         # Configuration
│   ├── db.py             # Database setup
│   ├── models.py         # SQLAlchemy models
│   ├── schemas.py        # Pydantic schemas
│   ├── services.py       # Business logic
│   ├── routes_orders.py  # Order endpoints
│   ├── routes_wallet.py  # Wallet endpoints
│   └── auth.py           # Authentication utilities
├── scripts/
│   ├── run_scenarios.py  # Test scenarios
│   └── seed_data.py      # Data seeding
├── requirements.txt
├── .gitignore
└── README.md
```

## Development

The application uses:
- FastAPI for the web framework
- SQLAlchemy 2.x for ORM
- PostgreSQL for the database
- Pydantic v2 for data validation

Database schema is automatically initialized on application startup.
