# Real-Time UPI Fraud Detection & Risk Scoring Pipeline

A complete, production-grade, event-driven UPI Fraud Detection and Risk Scoring system built with a clean microservices monorepo architecture.

---

## 1. Architecture Overview

```mermaid
flowchart TD
    subgraph Ingestion ["1. Client / Gateway Layer"]
        Sim["simulator.py\n(Normal + Attack Scenarios)"]
        Dash["React Dashboard\n(Fraud Ops Center :5173)"]
    end

    subgraph ServiceLayer ["2. Transaction Service (Spring Boot 3.x :8080)"]
        API["POST /api/v1/transactions\n(Idempotency Check)"]
        Cache["Redis 7\n(24h Key Cache)"]
        DB[(PostgreSQL 15\nTransactions Table)]
        KProd["Kafka Producer\n(upi.transactions.raw)"]
        KCons["Kafka Consumer\n(upi.transactions.scored)"]
    end

    subgraph Streaming ["3. Apache Kafka Streaming"]
        RawTopic[["Topic: upi.transactions.raw"]]
        ScoredTopic[["Topic: upi.transactions.scored"]]
    end

    subgraph MLRiskEngine ["4. Risk Engine Service (FastAPI + ML :8000)"]
        EngineConsumer["Kafka Consumer"]
        
        subgraph HybridRules ["Hybrid Scoring Engine (0 - 100)"]
            Vel["1. Velocity Check (Redis)\n> 3 txns / 5 mins (+40 pts)"]
            Travel["2. Impossible Travel (Redis)\nCity change within 15m (+50 pts)"]
            ML["3. IsolationForest ML Anomaly\nOutlier profile (0-30 pts)"]
        end
        
        Breaker{"Circuit Breaker\nTotal Score >= 75?"}
        Flag["Status: FLAGGED\nClear Flag Reason"]
        Approve["Status: APPROVED"]
        EngineProducer["Kafka Producer"]
    end

    Sim -->|HTTP POST with Idempotency-Key| API
    API <-->|Check / Set 24h TTL| Cache
    API -->|Write PENDING state| DB
    API -->|Publish Event| KProd
    KProd --> RawTopic
    
    RawTopic --> EngineConsumer
    EngineConsumer --> Vel
    EngineConsumer --> Travel
    EngineConsumer --> ML
    Vel --> Breaker
    Travel --> Breaker
    ML --> Breaker
    
    Breaker -->|Yes| Flag
    Breaker -->|No| Approve
    Flag --> EngineProducer
    Approve --> EngineProducer
    EngineProducer --> ScoredTopic
    
    ScoredTopic --> KCons
    KCons -->|Update Status, Risk Score & Reason| DB
    
    Dash -->|Polls GET /api/v1/transactions| API
    Dash -->|PATCH /review (Approve / Block)| API
```

---

## 2. Monorepo Structure

```
upi-fraud-detection/
├── docker-compose.yml          # Zookeeper, Kafka, PostgreSQL 15, Redis 7, & All Services
├── .env.example                # Config template
├── README.md                   # Complete documentation & quickstart
├── simulator.py                # Realistic simulator with 20 normal txns + 3 attack scenarios
├── postgres/
│   └── init.sql                # DB schema & performance indices
├── transaction-service/        # Java 17 + Spring Boot 3.2.5 + Maven
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/java/com/upi/fraud/
│       ├── TransactionServiceApplication.java
│       ├── config/             # KafkaConfig, RedisConfig, CorsConfig
│       ├── controller/         # REST API endpoints
│       ├── dto/                # Request / Response / Event payloads
│       ├── entity/             # JPA Entity & Status Enum
│       ├── repository/         # Spring Data JPA repository
│       └── service/            # Core business logic, Kafka consumer/producer, Idempotency
├── risk-engine-service/        # Python 3.11 + FastAPI + Scikit-Learn
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # FastAPI endpoints & Lifespan hook
│   ├── model.py                # Synthetic dataset generation & IsolationForest model
│   ├── rules.py                # Sliding window velocity + Impossible travel heuristics
│   ├── pipeline.py             # Kafka background event processing loop
│   └── tests/                  # Unit tests (fakeredis, model validation)
└── dashboard/                  # React + Vite + Tailwind CSS
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── tailwind.config.js
    └── src/
        ├── App.jsx             # Main dashboard shell & polling loop (2s)
        ├── components/
        │   ├── KpiCards.jsx    # Real-time metrics (Total, Volume, Flagged)
        │   ├── TransactionTable.jsx # Interactive feed & review actions
        │   └── RiskBadge.jsx   # Visual risk badge (Green / Amber / Red)
```

---

## 3. Hybrid Risk Scoring Specifications

Every transaction receives a score between **0 and 100**:

| Rule / Check | Mechanism | Weight | Condition |
| :--- | :--- | :--- | :--- |
| **Velocity Check** | Redis Sorted Set (`ZADD` / `ZREMRANGEBYSCORE`) | **+40 pts** | Sender completes $>3$ transactions in sliding 5-min window |
| **Impossible Travel** | Redis TTL Key (`SETEX` 900s) | **+50 pts** | Sender originates from a different city within 15 minutes |
| **ML Anomaly Score** | Scikit-learn `IsolationForest` | **0–30 pts** | Analyzes amount & frequency distribution, mapping decision function to points |
| **High Value Outlier**| Outlier threshold safeguard | **+30 pts** | Amounts $\ge ₹50,000$ trigger anomaly flag |

### Circuit Breaker
- If **$\text{Risk Score} \ge 75$**: Marked as **`FLAGGED`** with descriptive reasons (e.g., `Impossible travel: Bengaluru to Delhi in 0.1 mins | ML Anomaly Alert: outlier profile`).
- Otherwise: Marked as **`APPROVED`**.

---

## 4. Quickstart Guide (Run with Docker Compose)

### Prerequisites
- Docker Engine & Docker Compose installed.

### 1-Step Full Stack Launch
From the `upi-fraud-detection/` directory:
```bash
docker compose up --build -d
```

This launches all 7 containers:
1. `upi-zookeeper` (Port 2181)
2. `upi-kafka` (Port 9092, 29092)
3. `upi-postgres` (Port 5432)
4. `upi-redis` (Port 6379)
5. `upi-transaction-service` (Port 8080)
6. `upi-risk-engine-service` (Port 8000)
7. `upi-dashboard` (Port 5173)

Check status:
```bash
docker compose ps
```

---

## 5. Running the Simulator

Run the traffic generator to simulate normal user transactions and 3 fraud attacks:

```bash
# Install requests if running on host
pip install requests

# Execute simulation
python simulator.py
```

### What the Simulator Does:
1. **20 Normal Transactions:** Micro and moderate payments (`₹50` to `₹2,000`) across stable cities.
2. **Attack 1 (Velocity Burst):** 5 transactions within 10 seconds from `burst.attacker@okaxis`.
3. **Attack 2 (Impossible Travel):** Transaction in Bengaluru followed immediately by Delhi within 1 minute from `teleport.hacker@okhdfc`.
4. **Attack 3 (High-Value Outlier):** Transaction of `₹95,000.00` from `account_takeover@oksbi`.

---

## 6. Accessing the Services & Dashboard

- **Operations Dashboard:** [http://localhost:5173](http://localhost:5173)
- **Transaction Service API:** [http://localhost:8080/api/v1/transactions](http://localhost:8080/api/v1/transactions)
- **Spring Actuator Health:** [http://localhost:8080/actuator/health](http://localhost:8080/actuator/health)
- **Risk Engine Health:** [http://localhost:8000/health](http://localhost:8000/health)

---

## 7. API Reference

### 1. Ingest Transaction
`POST /api/v1/transactions`
- **Header:** `Idempotency-Key: <unique-uuid>`
- **Request Body:**
```json
{
  "senderUpi": "rohit@okhdfc",
  "receiverUpi": "swiggy@icici",
  "amount": 450.00,
  "city": "Mumbai",
  "deviceId": "dev_and_101"
}
```
- **Response (201 Created):**
```json
{
  "transactionId": "550e8400-e29b-41d4-a716-446655440000",
  "senderUpi": "rohit@okhdfc",
  "receiverUpi": "swiggy@icici",
  "amount": 450.00,
  "city": "Mumbai",
  "deviceId": "dev_and_101",
  "status": "PENDING",
  "riskScore": 0,
  "flagReason": null,
  "createdAt": "2026-11-21T10:30:00Z"
}
```

### 2. Fetch Recent Transactions
`GET /api/v1/transactions?limit=50&status=FLAGGED`
- Returns array of recent transactions with updated `risk_score` and `flag_reason`.

### 3. Analyst Review (Approve or Block)
`PATCH /api/v1/transactions/{id}/review`
- **Request Body:**
```json
{
  "status": "APPROVED",
  "reviewNotes": "Customer confirmed travel via flight"
}
```
*(or `"status": "BLOCKED"` to confirm fraudulent activity)*
