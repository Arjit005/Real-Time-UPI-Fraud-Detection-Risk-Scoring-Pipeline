import os
import time
import uuid
import random
import requests

API_URL = os.getenv("TRANSACTION_API_URL", "http://localhost:8080/api/v1/transactions")

CITIES = ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai", "Kolkata", "Jaipur"]
USERS = [
    ("rohit.sharma@okhdfc", "dev_and_101", "Mumbai"),
    ("priya.patel@okaxis", "dev_ios_202", "Bengaluru"),
    ("aravind.kumar@oksbi", "dev_and_303", "Chennai"),
    ("sneha.rao@okicici", "dev_ios_404", "Hyderabad"),
    ("vikram.aditya@paytm", "dev_and_505", "Delhi"),
]
MERCHANTS = [
    "swiggy@icici", "zomato@hdfcbank", "amazon@axisbank",
    "blinkit@kotak", "zepto@sbi", "dmart@rbl", "flipkart@axisbank"
]


def post_transaction(payload, idempotency_key=None):
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": os.getenv("ANALYST_API_KEY", "")
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=5)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"error": "Non-JSON response", "text": response.text}
    except Exception as e:
        return 500, {"error": str(e)}


def run_simulator():
    print("=" * 75)
    print("🚀 STARTING REAL-TIME UPI TRAFFIC SIMULATOR")
    print(f"Target: {API_URL}")
    print("=" * 75)

    # -------------------------------------------------------------
    # Phase 1: 20 Normal UPI Transactions (₹50 – ₹2,000, consistent cities)
    # -------------------------------------------------------------
    print("\n🟢 [PHASE 1] Generating 20 Realistic Normal UPI Transactions...")
    for i in range(1, 21):
        sender, device, city = random.choice(USERS)
        receiver = random.choice(MERCHANTS)
        amount = round(random.uniform(50.0, 2000.0), 2)
        idem_key = str(uuid.uuid4())

        payload = {
            "senderUpi": sender,
            "receiverUpi": receiver,
            "amount": amount,
            "city": city,
            "deviceId": device
        }

        status, body = post_transaction(payload, idem_key)
        txn_id = body.get("transactionId", "FAILED")
        print(f"  [{i:02d}/20] Normal Txn: ₹{amount:>7.2f} from {sender:<20} in {city:<10} -> HTTP {status} (ID: {str(txn_id)[:8]})")
        time.sleep(0.3)

    print("\n✅ Phase 1 Complete: 20 Normal Transactions submitted.")
    time.sleep(2)

    # -------------------------------------------------------------
    # Phase 2: Attack Scenario 1 - Rapid Velocity Burst
    # (5 transactions in rapid succession for the same sender within 10s)
    # -------------------------------------------------------------
    print("\n🔴 [PHASE 2] Attack Scenario 1: Rapid Velocity Burst (5 txns in < 10s)")
    velocity_user = "burst.attacker@okaxis"
    velocity_device = "dev_sim_burst_99"
    for j in range(1, 6):
        payload = {
            "senderUpi": velocity_user,
            "receiverUpi": f"mule_wallet_{j}@paytm",
            "amount": 2500.0 + (j * 100),
            "city": "Bengaluru",
            "deviceId": velocity_device
        }
        status, body = post_transaction(payload, str(uuid.uuid4()))
        print(f"  ⚡ [Burst {j}/5] ₹{payload['amount']:.2f} sent by {velocity_user} -> HTTP {status}")
        time.sleep(0.4)

    print("✅ Attack Scenario 1 executed.")
    time.sleep(2)

    # -------------------------------------------------------------
    # Phase 3: Attack Scenario 2 - Impossible Travel
    # (Bengaluru -> Delhi within 1 minute for same sender)
    # -------------------------------------------------------------
    print("\n🔴 [PHASE 3] Attack Scenario 2: Impossible Travel (Bengaluru -> Delhi in < 1 min)")
    travel_user = "teleport.hacker@okhdfc"
    travel_device = "dev_rooted_x90"

    # Step A: First txn in Bengaluru
    print("  📍 Step A: Initiating transaction from Bengaluru...")
    payload_a = {
        "senderUpi": travel_user,
        "receiverUpi": "luxury_store@icici",
        "amount": 1200.0,
        "city": "Bengaluru",
        "deviceId": travel_device
    }
    status_a, body_a = post_transaction(payload_a, str(uuid.uuid4()))
    print(f"     Sent from Bengaluru -> HTTP {status_a} (Response: {body_a.get('status', body_a)})")

    print("  ⏳ Waiting 3 seconds (simulating instant geographical jump)...")
    time.sleep(3)

    # Step B: Second txn in Delhi
    print("  📍 Step B: Initiating transaction from Delhi with same account...")
    payload_b = {
        "senderUpi": travel_user,
        "receiverUpi": "cashout_atm@sbi",
        "amount": 15000.0,
        "city": "Delhi",
        "deviceId": travel_device
    }
    status_b, body_b = post_transaction(payload_b, str(uuid.uuid4()))
    print(f"     Sent from Delhi -> HTTP {status_b} (Response: {body_b.get('status', body_b)})")
    print("✅ Attack Scenario 2 executed.")
    time.sleep(2)

    # -------------------------------------------------------------
    # Phase 4: Attack Scenario 3 - High-Value Outlier
    # (₹95,000 transaction - anomalous compared to normal distribution)
    # -------------------------------------------------------------
    print("\n🔴 [PHASE 4] Attack Scenario 3: High-Value Outlier (₹95,000)")
    outlier_user = "account_takeover@oksbi"
    payload_outlier = {
        "senderUpi": outlier_user,
        "receiverUpi": "crypto_exchange@yesbank",
        "amount": 95000.00,
        "city": "Mumbai",
        "deviceId": "dev_emulator_vbox"
    }
    status_o, body_o = post_transaction(payload_outlier, str(uuid.uuid4()))
    print(f"  💎 High-value Txn: ₹95,000.00 from {outlier_user} -> HTTP {status_o}")
    print("✅ Attack Scenario 3 executed.")

    # -------------------------------------------------------------
    # Phase 5: Verification & Verification of Scored Pipeline
    # -------------------------------------------------------------
    print("\n⏳ Waiting 5 seconds for Kafka event scoring & DB updates to settle...")
    time.sleep(5)

    print("\n📊 Fetching latest 10 scored transactions from Transaction Service...")
    try:
        headers = {"X-API-Key": os.getenv("ANALYST_API_KEY", "")}
        res = requests.get(f"{API_URL}?limit=10", headers=headers, timeout=5)
        if res.ok:
            try:
                records = res.json()
            except ValueError:
                records = None

            if not isinstance(records, list):
                print(f"⚠️ Unexpected transaction response shape: {records}")
                return

            print("-" * 110)
            print(f"{'TXN ID':<10} | {'SENDER':<24} | {'AMOUNT':<10} | {'STATUS':<10} | {'RISK':<6} | {'REASON'}")
            print("-" * 110)
            for r in records:
                t_id = r.get("transactionId", "")[:8]
                sender = r.get("senderUpi", "")[:24]
                amt = f"₹{float(r.get('amount', 0)):.2f}"
                st = r.get("status", "")
                risk = f"{r.get('riskScore', 0)}"
                reason = r.get("flagReason", "") or "Normal"
                print(f"{t_id:<10} | {sender:<24} | {amt:<10} | {st:<10} | {risk:<6} | {reason[:40]}")
            print("-" * 110)
        else:
            print(f"⚠️ Fetching transactions returned HTTP {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Failed to fetch verification status: {e}")

    print("\n🎉 SIMULATION SCRIPT COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    run_simulator()
