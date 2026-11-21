import os
import uuid
import datetime
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor
import valkey
from confluent_kafka import Producer

# Configuration loaded securely from environment variables
POSTGRES_URL = os.getenv(
    "SPRING_DATASOURCE_URL",
    "postgres://avnadmin:password@pg-2bc95907-arjit04554-af81.k.aivencloud.com:10456/defaultdb?sslmode=require"
)
REDIS_HOST = os.getenv("REDIS_HOST", "valkey-2a2e80e0-arjit04554-af81.k.aivencloud.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "10457"))
REDIS_USER = os.getenv("REDIS_USER", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "password")

VALKEY_URI = f"valkeys://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-145b778f-arjit04554-af81.a.aivencloud.com:10469")
KAFKA_USER = os.getenv("KAFKA_SASL_USERNAME", "avnadmin")
KAFKA_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "password")
CA_PATH = os.path.abspath(os.getenv("KAFKA_SSL_CA_LOCATION", os.path.join(os.path.dirname(__file__), "ca.pem")))

try:
    valkey_client = valkey.from_url(VALKEY_URI)
except Exception:
    valkey_client = None

producer_conf = {
    'bootstrap.servers': KAFKA_BOOTSTRAP,
    'security.protocol': 'SASL_SSL',
    'sasl.mechanisms': 'SCRAM-SHA-256',
    'sasl.username': KAFKA_USER,
    'sasl.password': KAFKA_PASSWORD,
}
if os.path.exists(CA_PATH):
    producer_conf['ssl.ca.location'] = CA_PATH

try:
    kafka_producer = Producer(producer_conf)
except Exception:
    kafka_producer = None

app = FastAPI(title="UPI Production-Grade Banking Gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    return psycopg2.connect(POSTGRES_URL)


class TransactionRequest(BaseModel):
    senderUpi: str = Field(..., pattern=r"^[\w\.\-]+@[\w\-]+$")
    receiverUpi: str = Field(..., pattern=r"^[\w\.\-]+@[\w\-]+$")
    amount: float = Field(..., gt=0.0)
    city: str
    deviceId: str


class ReviewRequest(BaseModel):
    status: str
    reviewNotes: str = ""


@app.post("/api/v1/transactions")
def create_transaction(req: TransactionRequest, idempotency_key: str = Header(None, alias="Idempotency-Key")):
    # 1. Idempotency Check in Valkey (Zero duplicate insert)
    if idempotency_key and valkey_client:
        cached = valkey_client.get(f"upi:idempotency:{idempotency_key}")
        if cached:
            import json
            return json.loads(cached.decode())

    txn_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)

    # 2. Save PENDING record
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        INSERT INTO transactions (transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', 0, NULL, NULL, %s)
        RETURNING transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at;
        """,
        (txn_id, req.senderUpi, req.receiverUpi, req.amount, req.city, req.deviceId, now)
    )
    saved = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    response_data = {
        "transactionId": str(saved["transaction_id"]),
        "senderUpi": saved["sender_upi"],
        "receiverUpi": saved["receiver_upi"],
        "amount": float(saved["amount"]),
        "city": saved["city"],
        "deviceId": saved["device_id"],
        "status": saved["status"],
        "riskScore": saved["risk_score"] or 0,
        "flagReason": saved["flag_reason"],
        "scoreBreakdown": saved["score_breakdown"],
        "createdAt": saved["created_at"].isoformat() if saved["created_at"] else now.isoformat()
    }

    # 3. Stream to Kafka
    if kafka_producer:
        import json
        kafka_producer.produce(
            "upi.transactions.raw",
            key=req.senderUpi.encode("utf-8"),
            value=json.dumps(response_data).encode("utf-8")
        )
        kafka_producer.flush()

    # 4. Cache idempotency key for 24 hours
    if idempotency_key and valkey_client:
        import json
        valkey_client.set(f"upi:idempotency:{idempotency_key}", json.dumps(response_data), ex=86400)

    return response_data


@app.get("/api/v1/transactions")
def get_recent_transactions(limit: int = 50, status: str = None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if status and status.upper() != "ALL":
        cur.execute(
            """
            SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at
            FROM transactions
            WHERE status = %s
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (status.upper(), limit)
        )
    else:
        cur.execute(
            """
            SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at
            FROM transactions
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "transactionId": str(r["transaction_id"]),
            "senderUpi": r["sender_upi"],
            "receiverUpi": r["receiver_upi"],
            "amount": float(r["amount"]),
            "city": r["city"],
            "deviceId": r["device_id"],
            "status": r["status"],
            "riskScore": r["risk_score"] or 0,
            "flagReason": r["flag_reason"],
            "scoreBreakdown": r["score_breakdown"],
            "createdAt": r["created_at"].isoformat() if r["created_at"] else None
        })
    return result


@app.patch("/api/v1/transactions/{txn_id}/review")
def review_transaction(txn_id: str, req: ReviewRequest):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT status FROM transactions WHERE transaction_id = %s;", (txn_id,))
    prev = cur.fetchone()
    if not prev:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Transaction not found")

    prev_status = prev["status"]
    new_status = req.status.upper()

    # 1. Update Transaction
    cur.execute(
        """
        UPDATE transactions
        SET status = %s,
            flag_reason = COALESCE(flag_reason, '') || ' | Analyst: ' || %s
        WHERE transaction_id = %s
        RETURNING transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at;
        """,
        (new_status, req.reviewNotes, txn_id)
    )
    updated = cur.fetchone()

    # 2. Banking Compliance: Save Audit Trail
    cur.execute(
        """
        INSERT INTO audit_logs (transaction_id, action, analyst_notes, previous_status, new_status, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW());
        """,
        (txn_id, "MANUAL_REVIEW", req.reviewNotes, prev_status, new_status)
    )

    conn.commit()
    cur.close()
    conn.close()

    return {
        "transactionId": str(updated["transaction_id"]),
        "senderUpi": updated["sender_upi"],
        "receiverUpi": updated["receiver_upi"],
        "amount": float(updated["amount"]),
        "city": updated["city"],
        "deviceId": updated["device_id"],
        "status": updated["status"],
        "riskScore": updated["risk_score"] or 0,
        "flagReason": updated["flag_reason"],
        "scoreBreakdown": updated["score_breakdown"],
        "createdAt": updated["created_at"].isoformat() if updated["created_at"] else None
    }
