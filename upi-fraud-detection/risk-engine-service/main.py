import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import valkey

load_dotenv(find_dotenv(usecwd=True))
# Fallback to repository root .env if running from local mono-repo workspace
repo_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
if os.path.exists(repo_env):
    load_dotenv(repo_env)

from model import get_or_load_model
from rules import evaluate_transaction_risk
from pipeline import RiskPipelineWorker

REDIS_HOST = os.getenv("REDIS_HOST", "valkey-2a2e80e0-arjit04554-af81.k.aivencloud.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "10457"))
REDIS_USER = os.getenv("REDIS_USER", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

valkey_client = None
ml_model = None
pipeline_worker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global valkey_client, ml_model, pipeline_worker
    print("[FastAPI] Initializing Live Risk Engine Service...")

    if not REDIS_PASSWORD:
        print("[FastAPI] Warning: REDIS_PASSWORD environment variable not configured.")
        valkey_client = None
    else:
        import urllib.parse
        encoded_user = urllib.parse.quote_plus(REDIS_USER)
        encoded_pass = urllib.parse.quote_plus(REDIS_PASSWORD)
        valkey_uri = f"valkeys://{encoded_user}:{encoded_pass}@{REDIS_HOST}:{REDIS_PORT}"
        try:
            valkey_client = valkey.from_url(
                valkey_uri,
                socket_timeout=3.0,
                socket_connect_timeout=3.0
            )
            valkey_client.ping()
            print("[FastAPI] Successfully connected and pinged Valkey!")
        except Exception as e:
            print(f"[FastAPI] Failed to connect/ping Valkey: {e}")
            valkey_client = None

    ml_model = get_or_load_model()

    if valkey_client:
        pipeline_worker = RiskPipelineWorker(valkey_client, ml_model)
        pipeline_worker.start()

    yield

    if pipeline_worker:
        pipeline_worker.stop()
    if valkey_client:
        valkey_client.close()
    print("[FastAPI] Shutdown complete.")


app = FastAPI(
    title="UPI Risk Engine Service",
    description="Live Real-Time Hybrid ML + Rules Fraud Scoring Pipeline",
    version="1.0.0",
    lifespan=lifespan
)

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


class ScoreRequest(BaseModel):
    transactionId: str = "test-uuid"
    senderUpi: str
    receiverUpi: str
    amount: float
    city: str
    deviceId: str


@app.get("/health")
def health():
    valkey_alive = False
    try:
        valkey_alive = bool(valkey_client and valkey_client.ping())
    except Exception:
        pass

    pipeline_alive = bool(
        pipeline_worker and pipeline_worker.running and pipeline_worker.thread and pipeline_worker.thread.is_alive()
    )
    is_healthy = valkey_alive and (ml_model is not None) and pipeline_alive
    return {
        "status": "UP" if is_healthy else "DEGRADED",
        "cloud_valkey_connected": valkey_alive,
        "model_loaded": ml_model is not None,
        "kafka_pipeline_running": pipeline_alive
    }


@app.post("/api/v1/score")
def score_transaction(req: ScoreRequest):
    if not ml_model or not valkey_client:
        raise HTTPException(status_code=503, detail="Risk Engine not fully initialized")

    scored = evaluate_transaction_risk(valkey_client, ml_model, req.model_dump())
    return scored


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
