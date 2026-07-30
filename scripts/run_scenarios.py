#!/usr/bin/env python3
import requests
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import random


class ScenarioRunner:
    def __init__(self, base_url: str, customer_id: str):
        self.base_url = base_url
        self.customer_id = customer_id
    
    def ensure_user(self):
        """Ensure user exists."""
        print(f"Ensuring user exists for {self.customer_id}...")
        response = requests.get(f"{self.base_url}/users/{self.customer_id}")
        if response.status_code == 404:
            print(f"Creating user {self.customer_id}...")
            requests.post(
                f"{self.base_url}/users",
                json={
                    "user_id": self.customer_id,
                    "email": f"{self.customer_id.lower()}@example.com",
                    "full_name": f"Test User {self.customer_id}",
                    "phone": "+91-9876543210"
                }
            )
    
    def ensure_wallet(self):
        """Ensure wallet exists with initial balance."""
        self.ensure_user()
        print(f"Ensuring wallet exists for {self.customer_id}...")
        response = requests.get(f"{self.base_url}/wallet/{self.customer_id}")
        if response.status_code == 200:
            data = response.json()
            print(f"Wallet balance: {data['balance']}")
            if data['balance'] < 500:
                print("Topping up wallet...")
                requests.post(
                    f"{self.base_url}/wallet/{self.customer_id}/credit",
                    json={"amount": 1000.0}
                )
        elif response.status_code == 404:
            print("Creating wallet...")
            requests.post(
                f"{self.base_url}/wallet/{self.customer_id}/credit",
                json={"amount": 1000.0}
            )
    
    def orders_retry(self):
        """Scenario: Order creation with timeout and retry."""
        print("\n=== Running orders_retry scenario ===")
        
        idempotency_key = f"retry-test-{int(time.time())}"
        order_payload = {
            "customer_id": self.customer_id,
            "amount": 499.99,
            "currency": "INR",
            "idempotency_key": idempotency_key
        }
        
        print(f"Attempt 1: Creating order with idempotency_key={idempotency_key}")
        try:
            response1 = requests.post(
                f"{self.base_url}/orders",
                json=order_payload,
                timeout=1.0
            )
            print(f"Attempt 1 response: {response1.status_code} - {response1.json()}")
        except requests.exceptions.Timeout:
            print("Attempt 1: Request timed out")
        
        print("\nAttempt 2: Retrying same order...")
        try:
            response2 = requests.post(
                f"{self.base_url}/orders",
                json=order_payload,
                timeout=5.0
            )
            print(f"Attempt 2 response: {response2.status_code} - {response2.json()}")
        except requests.exceptions.Timeout:
            print("Attempt 2: Request timed out")
        
        time.sleep(1)
        
        print(f"\nFetching all orders for {self.customer_id}...")
        response = requests.get(f"{self.base_url}/orders?customer_id={self.customer_id}")
        orders = response.json()
        
        matching_orders = [o for o in orders if o.get('idempotency_key') == idempotency_key]
        print(f"Orders with idempotency_key={idempotency_key}: {len(matching_orders)}")
        
        for order in matching_orders:
            print(f"  - Order ID: {order['id']}, Amount: {order['amount']}")
    
    def wallet_concurrency(self):
        """Scenario: Concurrent wallet operations."""
        print("\n=== Running wallet_concurrency scenario ===")
        
        self.ensure_wallet()
        
        print("\nSetting up wallet with known balance...")
        response = requests.post(
            f"{self.base_url}/wallet/{self.customer_id}/credit",
            json={"amount": 500.0}
        )
        
        time.sleep(0.5)
        
        initial_response = requests.get(f"{self.base_url}/wallet/{self.customer_id}")
        initial_balance = initial_response.json()['balance']
        print(f"Starting balance: {initial_balance}")
        
        num_operations = 25
        debit_amount = 10.0
        
        print(f"\nExecuting {num_operations} concurrent debits of {debit_amount} each...")
        
        def debit_operation(i):
            try:
                response = requests.post(
                    f"{self.base_url}/wallet/{self.customer_id}/debit",
                    json={"amount": debit_amount}
                )
                return response.status_code == 200
            except Exception as e:
                return False
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(debit_operation, i) for i in range(num_operations)]
            results = [f.result() for f in as_completed(futures)]
        
        successful = sum(results)
        print(f"Successful operations: {successful}/{num_operations}")
        
        time.sleep(0.5)
        
        final_response = requests.get(f"{self.base_url}/wallet/{self.customer_id}")
        final_balance = final_response.json()['balance']
        
        expected_balance = initial_balance - (successful * debit_amount)
        
        print(f"\nInitial balance: {initial_balance}")
        print(f"Expected final balance: {expected_balance}")
        print(f"Actual final balance: {final_balance}")
        print(f"Difference: {abs(expected_balance - final_balance)}")
    
    def false_success(self):
        """Scenario: API returns success on constraint violation."""
        print("\n=== Running false_success scenario ===")
        
        invalid_payload = {
            "customer_id": self.customer_id,
            "amount": 0,
            "currency": "INR",
            "idempotency_key": f"invalid-{int(time.time())}"
        }
        
        print(f"Creating order with amount=0 (violates constraint)...")
        response = requests.post(
            f"{self.base_url}/orders",
            json=invalid_payload
        )
        
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.json()}")
        
        time.sleep(0.5)
        
        print(f"\nVerifying order persistence...")
        orders_response = requests.get(f"{self.base_url}/orders?customer_id={self.customer_id}")
        orders = orders_response.json()
        
        matching = [o for o in orders if o.get('idempotency_key') == invalid_payload['idempotency_key']]
        print(f"Orders found with idempotency_key={invalid_payload['idempotency_key']}: {len(matching)}")
        
        if len(matching) == 0:
            print("Order was not persisted in database")
        else:
            print(f"Order found: {matching[0]}")
    
    def mixed(self):
        """Scenario: Mixed operations."""
        print("\n=== Running mixed scenario ===")
        
        self.ensure_wallet()
        
        operations = [
            ("credit", 200.0),
            ("order", 150.0),
            ("debit", 50.0),
            ("order", 300.0),
            ("credit", 100.0),
        ]
        
        random.shuffle(operations)
        
        for op_type, amount in operations:
            if op_type == "credit":
                print(f"\nCrediting {amount}...")
                requests.post(
                    f"{self.base_url}/wallet/{self.customer_id}/credit",
                    json={"amount": amount}
                )
            elif op_type == "debit":
                print(f"\nDebiting {amount}...")
                try:
                    requests.post(
                        f"{self.base_url}/wallet/{self.customer_id}/debit",
                        json={"amount": amount}
                    )
                except Exception:
                    pass
            elif op_type == "order":
                print(f"\nCreating order for {amount}...")
                requests.post(
                    f"{self.base_url}/orders",
                    json={
                        "customer_id": self.customer_id,
                        "amount": amount,
                        "currency": "INR"
                    },
                    timeout=5.0
                )
            
            time.sleep(0.2)
        
        print("\n=== Final state ===")
        wallet = requests.get(f"{self.base_url}/wallet/{self.customer_id}").json()
        print(f"Wallet balance: {wallet['balance']}")
        
        orders = requests.get(f"{self.base_url}/orders?customer_id={self.customer_id}").json()
        print(f"Total orders: {len(orders)}")


def main():
    parser = argparse.ArgumentParser(description="Run API test scenarios")
    parser.add_argument("--scenario", default="all", 
                       choices=["orders_retry", "wallet_concurrency", "false_success", "mixed", "all"],
                       help="Scenario to run")
    parser.add_argument("--base-url", default="http://localhost:8000",
                       help="Base URL of the API")
    parser.add_argument("--customer-id", default="CUST-001",
                       help="Customer ID to use")
    parser.add_argument("--seed", action="store_true",
                       help="Seed initial data")
    parser.add_argument("--repeat", type=int, default=1,
                       help="Number of times to repeat the scenario")
    
    args = parser.parse_args()
    
    runner = ScenarioRunner(args.base_url, args.customer_id)
    
    if args.seed:
        runner.ensure_wallet()
    
    scenarios = {
        "orders_retry": runner.orders_retry,
        "wallet_concurrency": runner.wallet_concurrency,
        "false_success": runner.false_success,
        "mixed": runner.mixed,
        "all": runner.mixed
    }
    
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n{'='*60}")
            print(f"Iteration {i+1}/{args.repeat}")
            print(f"{'='*60}")
        
        scenarios[args.scenario]()
        
        if i < args.repeat - 1:
            time.sleep(1)


if __name__ == "__main__":
    main()
