# Real-Time UPI Fraud Detection & Risk Scoring Pipeline

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel%20Production-success?style=for-the-badge&logo=vercel)](https://real-time-upi-fraud-detection-risk.vercel.app)
[![Java 21](https://img.shields.io/badge/Java-21%20LTS-orange?style=for-the-badge&logo=java)](https://openjdk.org/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-Streaming-red?style=for-the-badge&logo=apachekafka)](https://kafka.apache.org/)
[![Redis / Valkey](https://img.shields.io/badge/Redis-Valkey%207-critical?style=for-the-badge&logo=redis)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18%20Cloud-blue?style=for-the-badge&logo=postgresql)](https://postgresql.org)

An enterprise-grade, distributed event streaming pipeline engineered for **sub-50ms UPI transaction risk scoring, duplicate fraud prevention, and real-time operations center monitoring**. Built strictly mirroring the NPCI / Tier-1 Indian Banking Switch architecture (HDFC, Axis, ICICI).

---

## 1. System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer ["1. Client / Ingestion Layer"]
        Sim["simulator.py\n(Normal + Attack Vectors)"]
        WebDash["React Operations Center\n(Live on Vercel)"]
    end

    subgraph Gateway ["2. Transaction Gateway Layer (Port 8080)"]
        API["POST /api/v1/transactions\n(Strict VPA Regex & Decimal Validation)"]
        IdemCache["Valkey / Redis\n(Atomic SETNX 24h Idempotency)"]
        DB[(Aiven PostgreSQL 18\nTransactions Table)]
        KafkaProd["Kafka Producer\n(SASL_SSL SCRAM-256)"]
    end

    subgraph StreamEngine ["3. Distributed Event Streaming (Aiven Kafka)"]
        RawTopic[["Topic: upi.transactions.raw\n(2 Partitions, RF=2)"]]
        ScoredTopic[["Topic: upi.transactions.scored"]]
        DLQTopic[["Topic: upi.transactions.dlq\n(Zero-Loss Dead Letter Queue)"]]
    end

    subgraph RiskEngine ["4. Hybrid Risk Engine (FastAPI + ML :8000)"]
        EngineConsumer["Kafka Consumer Group"]
        
        subgraph RulesEngine ["Hybrid Rule & ML Scoring (0 to 100)"]
            Vel["1. Sliding Window Velocity (Redis ZSET)\n> 3 txns / 5 mins (+40 pts)"]
            Travel["2. Impossible Travel (Redis TTL)\nCity change within 15 mins (+50 pts)"]
            Base["3. Dynamic User Baseline (Redis)\nAmount > 5x historical rolling avg (+25 pts)"]
            ML["4. IsolationForest ML Outlier\nUnsupervised Anomaly Score (0–30 pts)"]
        end
        
        Breaker{"Circuit Breaker\nTotal Risk >= 75?"}
        DecisionFlag["Status: FLAGGED\nClear Flag Reasons"]
        DecisionPass["Status: APPROVED"]
    end

    subgraph AuditCompliance ["5. RBI Compliance & Operations"]
        AuditTable[(compliance.audit_logs\nImmutable Analyst Trail)]
    end

    Sim -->|POST with Idempotency-Key| API
    API <-->|Check / Cache 24h| IdemCache
    API -->|Write PENDING state| DB
    API -->|Publish Raw Event| KafkaProd
    KafkaProd --> RawTopic

    RawTopic --> EngineConsumer
    EngineConsumer -.->|Corrupt Payload Fallback| DLQTopic
    EngineConsumer --> Vel
    EngineConsumer --> Travel
    EngineConsumer --> Base
    EngineConsumer --> ML
    Vel --> Breaker
    Travel --> Breaker
    Base --> Breaker
    ML --> Breaker

    Breaker -->|Yes| DecisionFlag
    Breaker -->|No| DecisionPass
    DecisionFlag --> ScoredTopic
    DecisionPass --> ScoredTopic
    ScoredTopic --> DB

    WebDash -->|Polls Live Feed (2s)| DB
    WebDash -->|Analyst Manual Override (Approve / Block)| AuditTable
```

---

## 2. Key High-Leverage Features

| Feature | Engineering Mechanism | Business / Banking Impact |
| :--- | :--- | :--- |
| **Atomic Idempotency** | Redis `SET key value EX 86400 NX` | Guarantees **Zero duplicate debits** if customer retries or networks lag. |
| **Dead Letter Queue (DLQ)** | Kafka `upi.transactions.dlq` fallback | Guarantees **Zero Data Loss** on corrupted messages or model exceptions. |
| **Sliding-Window Velocity** | Redis Sorted Set (`ZREMRANGEBYSCORE` + `ZCARD`) | Flags automated card/UPI brute-force attacks within 5 mins. |
| **Impossible Travel Check** | Redis Geo-TTL state tracking | Flags instant cross-city jumps (e.g. Bengaluru $\rightarrow$ Delhi in 60s). |
| **Dynamic User Baseline** | Redis Rolling Window (Last 10 transactions) | Catches deviations $> 5\times$ user's typical spending without rigid rules. |
| **IsolationForest Anomaly** | Scikit-learn unsupervised outlier model | Discovers unknown multi-dimensional payment anomalies. |
| **Explainable AI (XAI)** | Feature contribution breakdown JSON | Transparent breakdown: Velocity, Geo, Baseline & ML points. |
| **RBI Audit Log Trail** | PostgreSQL `audit_logs` immutable table | Records every analyst manual Approve/Block override for regulatory compliance. |

---

## 3. End-to-End Test Suite Verification

### A. Pytest Test Results (`risk-engine-service`)
```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.2.0
collected 5 items

tests/test_engine.py::test_synthetic_data_shape PASSED                   [ 20%]
tests/test_engine.py::test_velocity_rule_trigger PASSED                  [ 40%]
tests/test_engine.py::test_impossible_travel_trigger PASSED              [ 60%]
tests/test_engine.py::test_dynamic_user_baseline_profiling PASSED        [ 80%]
tests/test_engine.py::test_circuit_breaker_boundary PASSED               [100%]

============================= 5 passed in 25.44s ==============================
```

### B. Unit Tests (`transaction-service`)
- `testProcessTransactionSuccess()`: Verifies PENDING state, Kafka emission, and cache write.
- `testIdempotencyKeyBlocksDuplicate()`: Verifies 2nd call returns cached response with 0 DB writes.
- `testUpdateScoredTransaction()`: Verifies score persistence & status transition.

---

## 4. Live Cloud Deployment

- 🌐 **Live Operations Center (Frontend):** [https://real-time-upi-fraud-detection-risk.vercel.app](https://real-time-upi-fraud-detection-risk.vercel.app)
- 🗄️ **Managed Database:** Aiven PostgreSQL 18
- ⚡ **Cache & State Store:** Aiven Valkey (Redis 7)
- 📡 **Event Streaming:** Aiven Apache Kafka (SASL_SSL)

---

## 5. Quickstart & Local Setup

### 1. Clone & Configure
```bash
git clone https://github.com/Arjit005/Real-Time-UPI-Fraud-Detection-Risk-Scoring-Pipeline.git
cd Real-Time-UPI-Fraud-Detection-Risk-Scoring-Pipeline/upi-fraud-detection
cp .env.example .env
```

### 2. Run with Docker Compose
```bash
docker compose up --build -d
```

### 3. Run Traffic & Attack Simulator
```bash
python simulator.py
```
Simulates:
1. **20 Normal Transactions:** Micro & standard merchant payments (₹50–₹2,000).
2. **Velocity Attack:** 5 burst payments in 10 seconds.
3. **Impossible Travel Attack:** Bengaluru followed by Delhi in 60 seconds.
4. **Outlier Cashout:** High-value ₹95,000 transaction.

---

## 6. Interview Architecture Defense Guide

1. **Why Redis Sorted Sets (`ZSET`) instead of simple atomic counters?**  
   *Simple counters reset on fixed clock boundaries (e.g. 12:00 to 12:05), allowing attackers to send 3 transactions at 12:04 and 3 at 12:05 without detection. Redis Sorted Set with timestamp scores calculates a true rolling 300-second window.*

2. **Why IsolationForest instead of Supervised Classification (RandomForest/XGBoost)?**  
   *UPI fraud datasets suffer from extreme class imbalance ($< 0.05\%$ fraud) and constantly evolving attack vectors. Supervised models only detect known historical patterns, whereas IsolationForest isolates anomalies in high-dimensional feature space without labels.*

3. **How does the system ensure Zero Data Loss on Kafka consumer failure?**  
   *Kafka offset commit is handled explicitly post-evaluation, backed by a Dead Letter Queue (`upi.transactions.dlq`) that traps malformed payloads or unhandled runtime exceptions.*
