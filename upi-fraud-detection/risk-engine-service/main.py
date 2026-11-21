import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import valkey

from model import get_or_load_model
from rules import evaluate_transaction_risk
from pipeline import RiskPipelineWorker

REDIS_HOST = os.getenv("REDIS_HOST", "valkey-2a2e80e0-arjit04554-af81.k.aivencloud.com")
REDIS_PORT = int(os.getenv("REDIS_PORT", "10457"))
REDIS_USER = os.getenv("REDIS_USER", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "password")

valkey_client = None
ml_model = None
pipeline_worker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global valkey_client, ml_model, pipeline_worker
    print("[FastAPI] Initializing Live Risk Engine Service...")

    valkey_uri = f"valkeys://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
    try:
        valkey_client = valkey.from_url(valkey_uri)
    except Exception:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

    return {
        "status": "UP",
        "cloud_valkey_connected": valkey_alive,
        "model_loaded": ml_model is not None,
        "kafka_pipeline_running": bool(pipeline_worker and pipeline_worker.running)
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
