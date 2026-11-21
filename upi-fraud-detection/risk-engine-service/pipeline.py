import os
import json
import time
import threading
from confluent_kafka import Consumer, Producer
import valkey
from rules import evaluate_transaction_risk

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-145b778f-arjit04554-af81.a.aivencloud.com:10469")
KAFKA_USER = os.getenv("KAFKA_SASL_USERNAME", "avnadmin")
KAFKA_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "password")
CA_PATH = os.path.abspath(os.getenv("KAFKA_SSL_CA_LOCATION", os.path.join(os.path.dirname(__file__), "..", "ca.pem")))

RAW_TOPIC = os.getenv("TRANSACTION_RAW_TOPIC", "upi.transactions.raw")
SCORED_TOPIC = os.getenv("TRANSACTION_SCORED_TOPIC", "upi.transactions.scored")
DLQ_TOPIC = os.getenv("TRANSACTION_DLQ_TOPIC", "upi.transactions.dlq")
CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "upi-risk-engine-cloud-group")


class RiskPipelineWorker:
    def __init__(self, valkey_client: valkey.Valkey, ml_model):
        self.r = valkey_client
        self.model = ml_model
        self.running = False
        self.consumer = None
        self.producer = None
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"[Pipeline] RiskPipelineWorker started consuming from '{RAW_TOPIC}' with DLQ fallback on '{DLQ_TOPIC}'...")

    def stop(self):
        self.running = False
        if self.consumer:
            try:
                self.consumer.close()
            except Exception:
                pass
        print("[Pipeline] RiskPipelineWorker stopped.")

    def _init_kafka(self):
        producer_conf = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'SCRAM-SHA-256',
            'sasl.username': KAFKA_USER,
            'sasl.password': KAFKA_PASSWORD,
        }
        if os.path.exists(CA_PATH):
            producer_conf['ssl.ca.location'] = CA_PATH

        consumer_conf = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': CONSUMER_GROUP,
            'auto.offset.reset': 'latest',
            'enable.auto.commit': True,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'SCRAM-SHA-256',
            'sasl.username': KAFKA_USER,
            'sasl.password': KAFKA_PASSWORD,
        }
        if os.path.exists(CA_PATH):
            consumer_conf['ssl.ca.location'] = CA_PATH

        while self.running:
            try:
                print(f"[Pipeline] Connecting to Aiven Kafka at {KAFKA_BOOTSTRAP_SERVERS}...")
                self.producer = Producer(producer_conf)
                self.consumer = Consumer(consumer_conf)
                self.consumer.subscribe([RAW_TOPIC])
                print("[Pipeline] Connected to Aiven Kafka successfully!")
                return True
            except Exception as e:
                print(f"[Pipeline] Kafka not ready ({e}). Retrying in 4 seconds...")
                time.sleep(4)
        return False

    def send_to_dlq(self, raw_message_bytes, error_reason: str):
        """Zero Data Loss: Send unprocessable or failed messages to DLQ"""
        try:
            dlq_payload = json.dumps({
                "error": error_reason,
                "timestamp": time.time(),
                "failedPayload": raw_message_bytes.decode('utf-8', errors='replace')
            }).encode('utf-8')
            self.producer.produce(DLQ_TOPIC, value=dlq_payload)
            self.producer.flush()
            print(f"[DLQ] Dispatched message to {DLQ_TOPIC}: {error_reason}")
        except Exception as dlq_err:
            print(f"[DLQ] CRITICAL: Failed to publish to DLQ: {dlq_err}")

    def _run_loop(self):
        if not self._init_kafka():
            return

        while self.running:
            try:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    continue

                raw_bytes = msg.value()
                try:
                    txn = json.loads(raw_bytes.decode("utf-8"))
                except Exception as parse_err:
                    self.send_to_dlq(raw_bytes, f"JSON parse failure: {parse_err}")
                    continue

                txn_id = txn.get("transactionId", "unknown")
                sender = txn.get("senderUpi", "unknown")

                # Evaluate risk with Explainable AI & Dynamic Baseline
                try:
                    scored = evaluate_transaction_risk(self.r, self.model, txn)
                except Exception as eval_err:
                    self.send_to_dlq(raw_bytes, f"Evaluation logic failure: {eval_err}")
                    continue

                # Publish scored event including Explainable AI scoreBreakdown
                payload = json.dumps({
                    "transactionId": scored["transactionId"],
                    "senderUpi": scored["senderUpi"],
                    "receiverUpi": scored["receiverUpi"],
                    "amount": scored["amount"],
                    "city": scored["city"],
                    "deviceId": scored["deviceId"],
                    "status": scored["status"],
                    "riskScore": scored["riskScore"],
                    "flagReason": scored["flagReason"],
                    "scoreBreakdown": scored.get("scoreBreakdown")
                }).encode("utf-8")

                self.producer.produce(
                    SCORED_TOPIC,
                    key=sender.encode("utf-8") if sender else None,
                    value=payload
                )
                self.producer.flush()
                print(f"[Pipeline] Scored txn {txn_id}: Status={scored['status']}, Score={scored['riskScore']}")
            except Exception as e:
                if self.running:
                    print(f"[Pipeline] Consumer error: {e}. Reconnecting...")
                    time.sleep(2)
                    self._init_kafka()
