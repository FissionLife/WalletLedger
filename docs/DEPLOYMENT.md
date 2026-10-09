# WalletLedger - Local Deployment Guide

## Quick Start

This guide will help you set up and run the WalletLedger on your local machine in under 10 minutes.

---

## Prerequisites

Before you begin, ensure you have the following installed:

| Software | Version | Check Command       | Installation                                     |
| -------- | ------- | ------------------- | ------------------------------------------------ |
| Python   | 3.14+   | `python --version`  | [python.org](https://www.python.org/downloads/)  |
| uv       | Latest  | `uv --version`      | [astral.sh/uv](https://github.com/astral-sh/uv)  |
| Docker   | Latest  | `docker --version`  | [docker.com](https://www.docker.com/get-started) |
| Git      | Latest  | `git --version`     | [git-scm.com](https://git-scm.com/downloads)     |

---

## Step-by-Step Deployment

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd WalletLedger
```

### Step 2: Start PostgreSQL Database

Start a PostgreSQL 16 container using Docker:

```bash
docker run --name app_pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=appdb \
  -p 5432:5432 \
  -d postgres:16
```

**Verify PostgreSQL is running:**

```bash
docker ps | grep app_pg
```

Expected output:

```
CONTAINER ID   IMAGE         STATUS         PORTS
abc123def456   postgres:16   Up 2 seconds   0.0.0.0:5432->5432/tcp
```

**Check PostgreSQL logs** (optional):

```bash
docker logs app_pg
```

### Step 3: Install Dependencies with uv

Use `uv` to automatically sync the project environment and install all dependencies:

```bash
uv sync
```

*This automatically creates a `.venv` directory and installs the dependencies from `pyproject.toml` and `uv.lock`.*

### Step 4: (Optional) Activate Virtual Environment

With `uv`, commands can be run directly using `uv run <command>` without manual activation. However, if you wish to activate the virtual environment manually:

On macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows (PowerShell):

```bash
.venv\Scripts\Activate.ps1
```

On Windows (Command Prompt):

```bash
.venv\Scripts\activate.bat
```

### Step 5: Initialize Database Schema (Option A - Automatic)

The application automatically creates tables on startup. Just run:

```bash
uv run uvicorn main:app --reload --port 8000
```

The database schema will be created automatically.

### Step 5: Initialize Database Schema (Option B - Manual SQL)

If you prefer to create the schema manually:

```bash
# Connect to PostgreSQL
docker exec -it app_pg psql -U postgres -d appdb

# In psql prompt, run:
\i /path/to/WalletLedger/sql/schema.sql

# Or from command line:
docker exec -i app_pg psql -U postgres -d appdb < sql/schema.sql
```

### Step 6: Run the Application

```bash
uv run uvicorn main:app --reload --port 8000
```

**Expected output:**

```
INFO:     Will watch for changes in these directories: ['/path/to/WalletLedger']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReload
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 7: Verify Installation

**Test health endpoint:**

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{ "status": "healthy" }
```

**Access API documentation:**

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Step 8: Seed Sample Data (Optional)

**Option A: Using Python Script (Recommended)**

```bash
# Seed single user
uv run python scripts/seed_data.py CUST-001

# Seed multiple users
uv run python scripts/seed_data.py --all
```

**Option B: Using SQL File**

```bash
uv run python scripts/seed_demo_data.py
```

**Verify seeded data:**

```bash
curl http://localhost:8000/users/CUST-001
curl http://localhost:8000/wallet/CUST-001
curl "http://localhost:8000/orders?customer_id=CUST-001"
```

---

## Database Management

### Connecting to PostgreSQL

**Using psql (inside container):**

```bash
docker exec -it app_pg psql -U postgres -d appdb
```

**Common psql commands:**

```sql
\dt                          -- List all tables
\d users                     -- Describe users table
\d orders                    -- Describe orders table
\d wallets                   -- Describe wallets table

SELECT * FROM users;         -- View all users
SELECT * FROM wallets;       -- View all wallets
SELECT * FROM orders;        -- View all orders

\q                           -- Quit psql
```

### Database Operations

**View table counts:**

```sql
SELECT 'Users' AS table_name, COUNT(*) AS count FROM users
UNION ALL
SELECT 'Wallets', COUNT(*) FROM wallets
UNION ALL
SELECT 'Orders', COUNT(*) FROM orders;
```

**Clear all data (keep schema):**

```sql
TRUNCATE TABLE orders CASCADE;
TRUNCATE TABLE wallets CASCADE;
TRUNCATE TABLE users CASCADE;
```

**Drop and recreate database:**

```bash
docker exec -it app_pg psql -U postgres -c "DROP DATABASE appdb;"
docker exec -it app_pg psql -U postgres -c "CREATE DATABASE appdb;"
docker exec -i app_pg psql -U postgres -d appdb < sql/schema.sql
```

### PostgreSQL Container Management

**Stop PostgreSQL:**

```bash
docker stop app_pg
```

**Start PostgreSQL:**

```bash
docker start app_pg
```

**Restart PostgreSQL:**

```bash
docker restart app_pg
```

**Remove PostgreSQL container:**

```bash
docker stop app_pg
docker rm app_pg
```

**View PostgreSQL logs:**

```bash
docker logs app_pg
docker logs -f app_pg  # Follow logs in real-time
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root (optional):

```bash
# .env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/appdb
```

### Custom Database Configuration

If you want to use a different database:

```bash
# Start PostgreSQL with custom settings
docker run --name my_pg \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_USER=myuser \
  -e POSTGRES_DB=mydb \
  -p 5433:5432 \
  -d postgres:16

# Update .env file
echo "DATABASE_URL=postgresql+psycopg2://myuser:mypassword@localhost:5433/mydb" > .env

# Run application
uv run uvicorn main:app --reload --port 8000
```
