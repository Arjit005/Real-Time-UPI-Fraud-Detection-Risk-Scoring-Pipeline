import os
import uuid
import datetime
import hashlib
import json
from decimal import Decimal
from typing import Literal
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor
import valkey
from confluent_kafka import Producer

load_dotenv(find_dotenv(usecwd=True))

# Configuration loaded securely from environment variables
POSTGRES_URL = os.getenv("SPRING_DATASOURCE_URL") or os.getenv("DATABASE_URL")
if not POSTGRES_URL:
    raise RuntimeError("SPRING_DATASOURCE_URL or DATABASE_URL environment variable is required")

REDIS_HOST = os.getenv("REDIS_HOST", "valkey-2a2e80e0-arjit04554-af81.k.aivencloud.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "10457"))
REDIS_USER = os.getenv("REDIS_USER", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
if not REDIS_PASSWORD:
    raise RuntimeError("REDIS_PASSWORD environment variable is required")

VALKEY_URI = f"valkeys://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-145b778f-arjit04554-af81.a.aivencloud.com:10469")
KAFKA_USER = os.getenv("KAFKA_SASL_USERNAME", "avnadmin")
KAFKA_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD")
if not KAFKA_PASSWORD:
    raise RuntimeError("KAFKA_SASL_PASSWORD environment variable is required")
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

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ANALYST_API_KEY = os.getenv("ANALYST_API_KEY")

def verify_analyst_auth(x_api_key: str = Header(None, alias="X-API-Key"),
                        authorization: str = Header(None, alias="Authorization")):
    if not ANALYST_API_KEY:
        raise HTTPException(status_code=503, detail="Service Unavailable: Authentication service not configured")
    bearer = None
    if authorization:
        auth_parts = authorization.strip().split(" ", 1)
        if len(auth_parts) == 2 and auth_parts[0].lower() == "bearer":
            bearer = auth_parts[1].strip()
        else:
            bearer = authorization.strip()
    provided = x_api_key or bearer
    if not provided or provided != ANALYST_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing API key")


def get_db():
    return psycopg2.connect(POSTGRES_URL)


class TransactionRequest(BaseModel):
    senderUpi: str = Field(..., pattern=r"^[\w\.\-]+@[\w\-]+$")
    receiverUpi: str = Field(..., pattern=r"^[\w\.\-]+@[\w\-]+$")
    amount: Decimal = Field(..., gt=0.0, decimal_places=2, max_digits=12)
    city: str
    deviceId: str


class ReviewRequest(BaseModel):
    status: Literal["APPROVED", "BLOCKED"]
    reviewNotes: str = ""


def compute_payload_hash(req: TransactionRequest) -> str:
    amount_str = f"{req.amount:.2f}"
    raw = f"{req.senderUpi}|{req.receiverUpi}|{amount_str}|{req.city}|{req.deviceId}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

@app.post("/api/v1/transactions")
def create_transaction(req: TransactionRequest, idempotency_key: str = Header(None, alias="Idempotency-Key")):
    payload_hash = compute_payload_hash(req)
    idem_redis_key = f"upi:idempotency:{idempotency_key.strip()}" if idempotency_key else None

    # 1. Atomic Idempotency Claim in Valkey
    if idem_redis_key:
        if not valkey_client:
            raise HTTPException(status_code=503, detail="Idempotency store unavailable")
        initial_val = json.dumps({"payload_hash": payload_hash, "response": None})
        try:
            claimed = valkey_client.set(idem_redis_key, initial_val, nx=True, ex=300)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Idempotency store connection error: {e}")

        if not claimed:
            try:
                cached_raw = valkey_client.get(idem_redis_key)
            except Exception as e:
                raise HTTPException(status_code=503, detail=f"Idempotency store read error: {e}")
            if cached_raw:
                try:
                    cached_data = json.loads(cached_raw.decode("utf-8"))
                except Exception:
                    raise HTTPException(status_code=503, detail="Corrupted idempotency data in store")
                stored_hash = cached_data.get("payload_hash")
                if stored_hash and stored_hash != payload_hash:
                    raise HTTPException(status_code=409, detail="Idempotency key reused with different request payload")
                if cached_data.get("response"):
                    return cached_data["response"]
                else:
                    raise HTTPException(status_code=409, detail="Request already in progress for this idempotency key")
            else:
                raise HTTPException(status_code=409, detail="Request already in progress for this idempotency key")

    txn_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)

    # 2. Save PENDING record and stream to Kafka inside atomic transaction boundary
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO transactions (transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', 0, NULL, NULL, %s)
                    RETURNING transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at;
                    """,
                    (txn_id, req.senderUpi, req.receiverUpi, str(req.amount), req.city, req.deviceId, now)
                )
                saved = cur.fetchone()

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

                # 3. Stream to Kafka with delivery confirmation callback before DB commit
                if not kafka_producer:
                    conn.rollback()
                    raise HTTPException(status_code=503, detail="Kafka producer unavailable: message delivery not possible")

                delivery_error = []
                def delivery_report(err, msg):
                    if err is not None:
                        delivery_error.append(str(err))

                try:
                    kafka_producer.produce(
                        "upi.transactions.raw",
                        key=req.senderUpi.encode("utf-8"),
                        value=json.dumps(response_data).encode("utf-8"),
                        callback=delivery_report
                    )
                    remaining = kafka_producer.flush(timeout=5.0)
                    if remaining > 0 or len(delivery_error) > 0:
                        conn.rollback()
                        raise HTTPException(status_code=503, detail="Kafka delivery failure: message could not be delivered to stream")
                except HTTPException:
                    raise
                except Exception as k_err:
                    conn.rollback()
                    raise HTTPException(status_code=503, detail=f"Kafka produce error: {k_err}")

                conn.commit()
    except HTTPException:
        if idem_redis_key and valkey_client:
            try:
                valkey_client.delete(idem_redis_key)
            except Exception:
                pass
        raise
    except Exception as db_err:
        if idem_redis_key and valkey_client:
            try:
                valkey_client.delete(idem_redis_key)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Database error processing transaction")

    # 4. Cache full response with payload hash for 24 hours on success
    if idem_redis_key and valkey_client:
        cached_record = {"payload_hash": payload_hash, "response": response_data}
        try:
            valkey_client.set(idem_redis_key, json.dumps(cached_record), ex=86400)
        except Exception as e:
            print(f"[TransactionAPI] Warning: Failed to cache idempotency response in Valkey: {e}")

    return response_data


@app.get("/api/v1/transactions")
def get_recent_transactions(limit: int = 50, status: str = None, _auth: None = Depends(verify_analyst_auth)):
    clamped_limit = max(1, min(limit, 100))
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if status and status.upper() != "ALL":
                cur.execute(
                    """
                    SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at
                    FROM transactions
                    WHERE status = %s
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (status.upper(), clamped_limit)
                )
            else:
                cur.execute(
                    """
                    SELECT transaction_id, sender_upi, receiver_upi, amount, city, device_id, status, risk_score, flag_reason, score_breakdown, created_at
                    FROM transactions
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (clamped_limit,)
                )
            rows = cur.fetchall()

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
def review_transaction(txn_id: str, req: ReviewRequest, _auth: None = Depends(verify_analyst_auth)):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Row-level locking to prevent race conditions during concurrent review
                cur.execute("SELECT status FROM transactions WHERE transaction_id = %s FOR UPDATE;", (txn_id,))
                prev = cur.fetchone()
                if not prev:
                    raise HTTPException(status_code=404, detail="Transaction not found")

                prev_status = prev["status"]
                new_status = req.status.upper()

                if prev_status == "BLOCKED":
                    raise HTTPException(status_code=400, detail="Cannot transition a BLOCKED transaction: terminal state")
                if prev_status == new_status:
                    raise HTTPException(status_code=400, detail=f"Transaction is already in status {new_status}")

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
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TransactionAPI] Database error during review execution: {e}")
        raise HTTPException(status_code=500, detail="Database error during review execution")

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
