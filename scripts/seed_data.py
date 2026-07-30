#!/usr/bin/env python3
import requests
import sys

BASE_URL = "http://localhost:8000"


def seed_user(user_id: str, email: str, full_name: str, phone: str = None):
    """Create a user."""
    print(f"Creating user {user_id}...")
    
    response = requests.post(
        f"{BASE_URL}/users",
        json={
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "phone": phone
        }
    )
    
    if response.status_code == 201:
        data = response.json()
        print(f"✓ User created: {data['user_id']} - {data['full_name']} ({data['email']})")
        return True
    else:
        print(f"✗ Failed to create user: {response.status_code}")
        if response.status_code != 404:
            print(f"  {response.text}")
        return False


def seed_wallet(customer_id: str, initial_balance: float = 1000.0):
    """Initialize a wallet with starting balance."""
    print(f"Seeding wallet for {customer_id} with balance {initial_balance}...")
    
    response = requests.post(
        f"{BASE_URL}/wallet/{customer_id}/credit",
        json={"amount": initial_balance}
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Wallet created: {data['customer_id']} - Balance: {data['balance']}")
        return True
    else:
        print(f"✗ Failed to create wallet: {response.status_code}")
        print(f"  {response.text}")
        return False


def seed_orders(customer_id: str, count: int = 3):
    """Create sample orders."""
    print(f"\nCreating {count} sample orders for {customer_id}...")
    
    for i in range(count):
        amount = 100.0 + (i * 50)
        response = requests.post(
            f"{BASE_URL}/orders",
            json={
                "customer_id": customer_id,
                "amount": amount,
                "currency": "INR",
                "idempotency_key": f"seed-order-{customer_id}-{i}"
            },
            timeout=10.0
        )
        
        if response.status_code == 201:
            data = response.json()
            print(f"✓ Order created: {data['order_id']}")
        else:
            print(f"✗ Failed to create order: {response.status_code}")


def seed_multiple_users():
    """Seed multiple users with wallets and orders."""
    users = [
        ("CUST-001", "john.doe@example.com", "John Doe", "+91-9876543210"),
        ("CUST-002", "jane.smith@example.com", "Jane Smith", "+91-9876543211"),
        ("CUST-003", "bob.wilson@example.com", "Bob Wilson", "+91-9876543212"),
    ]
    
    print("=" * 60)
    print("Seeding multiple users")
    print("=" * 60)
    
    for user_id, email, full_name, phone in users:
        print(f"\n--- Processing {user_id} ---")
        if seed_user(user_id, email, full_name, phone):
            seed_wallet(user_id, 1000.0 + (int(user_id.split('-')[1]) * 500))
            seed_orders(user_id, 2)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        seed_multiple_users()
    else:
        customer_id = sys.argv[1] if len(sys.argv) > 1 else "CUST-001"
        email = sys.argv[2] if len(sys.argv) > 2 else f"{customer_id.lower()}@example.com"
        full_name = sys.argv[3] if len(sys.argv) > 3 else "Test User"
        
        print(f"Starting data seeding for customer: {customer_id}\n")
        
        if seed_user(customer_id, email, full_name, "+91-9876543210"):
            seed_wallet(customer_id, 1000.0)
            seed_orders(customer_id, 3)
        
        print("\n✓ Seeding complete!")


if __name__ == "__main__":
    main()
