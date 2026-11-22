import os
import json
import time
import threading
from confluent_kafka import Consumer, Producer
import valkey
from rules import evaluate_transaction_risk

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-145b778f-arjit04554-af81.a.aivencloud.com:10469")
KAFKA_USER = os.getenv("KAFKA_SASL_USERNAME")
KAFKA_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD")
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
        if self.producer:
            try:
                self.producer.flush(timeout=5.0)
            except Exception:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10.0)
        print("[Pipeline] RiskPipelineWorker stopped.")

    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def _init_kafka(self):
        if not KAFKA_USER or not KAFKA_PASSWORD:
            print("[Pipeline] Error: KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD required to initialize Kafka worker.")
            return False

        if self.consumer:
            try:
                self.consumer.close()
            except Exception:
                pass
            self.consumer = None
        if self.producer:
            try:
                self.producer.flush(timeout=3.0)
            except Exception:
                pass
            self.producer = None

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
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,
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

    def send_to_dlq(self, raw_message_bytes, error_reason: str) -> bool:
        """Zero Data Loss: Send unprocessable or failed messages to DLQ. Returns True if confirmed delivered."""
        try:
            failed_str = raw_message_bytes.decode('utf-8', errors='replace') if raw_message_bytes is not None else None
            dlq_payload = json.dumps({
                "error": error_reason,
                "timestamp": time.time(),
                "failedPayload": failed_str
            }).encode('utf-8')
            
            delivery_err = []
            def dlq_cb(err, msg):
                if err is not None:
                    delivery_err.append(str(err))

            self.producer.produce(DLQ_TOPIC, value=dlq_payload, callback=dlq_cb)
            remaining = self.producer.flush(timeout=5.0)
            if remaining == 0 and len(delivery_err) == 0:
                print(f"[DLQ] Dispatched message to {DLQ_TOPIC}: {error_reason}")
                return True
            else:
                print(f"[DLQ] CRITICAL: DLQ delivery failed (remaining={remaining}, errs={delivery_err})")
                return False
        except Exception as dlq_err:
            print(f"[DLQ] CRITICAL: Failed to publish to DLQ: {dlq_err}")
            return False

    def _seek_back(self, msg) -> bool:
        from confluent_kafka import TopicPartition
        try:
            tp = TopicPartition(msg.topic(), msg.partition(), msg.offset())
            self.consumer.seek(tp)
            time.sleep(1)
            return True
        except Exception as e:
            print(f"[Pipeline] Seek back failed: {e}. Reinitializing consumer to prevent offset progression.")
            try:
                self.consumer.close()
            except Exception:
                pass
            self.consumer = None
            return False

    def _commit_with_retry(self, msg, context: str) -> bool:
        for attempt in range(1, 4):
            try:
                partitions = self.consumer.commit(message=msg, asynchronous=False)
                if partitions:
                    failed_parts = [p for p in partitions if p.error is not None]
                    if failed_parts:
                        raise RuntimeError(f"Commit failed on partition(s): {failed_parts}")
                return True
            except Exception as commit_err:
                print(f"[Pipeline] Commit attempt {attempt} failed ({context}): {commit_err}")
                time.sleep(0.5)
        print(f"[Pipeline] CRITICAL: Commit failed after 3 attempts ({context}). Seeking back.")
        self._seek_back(msg)
        return False

    def _run_loop(self):
        if not self._init_kafka():
            return

        try:
            while self.running:
                if self.consumer is None:
                    if not self._init_kafka():
                        time.sleep(2)
                        continue

                try:
                    msg = self.consumer.poll(timeout=1.0)
                    if msg is None:
                        continue
                    if msg.error():
                        continue

                    raw_bytes = msg.value()
                    try:
                        if raw_bytes is None:
                            raise ValueError("Null Kafka message value (tombstone)")
                        txn = json.loads(raw_bytes.decode("utf-8"))
                        if not isinstance(txn, dict):
                            raise ValueError(f"Expected JSON object, got {type(txn).__name__}")
                    except Exception as parse_err:
                        dlq_ok = self.send_to_dlq(raw_bytes, f"JSON parse/validation failure: {parse_err}")
                        if dlq_ok:
                            self._commit_with_retry(msg, "parse_error")
                        else:
                            self._seek_back(msg)
                        continue

                    txn_id = txn.get("transactionId", "unknown")
                    sender = txn.get("senderUpi", "unknown")

                    # Evaluate risk with Explainable AI & Dynamic Baseline
                    try:
                        scored = evaluate_transaction_risk(self.r, self.model, txn)
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
                    except Exception as eval_err:
                        dlq_ok = self.send_to_dlq(raw_bytes, f"Evaluation logic/serialization failure: {eval_err}")
                        if dlq_ok:
                            self._commit_with_retry(msg, "eval_error")
                        else:
                            self._seek_back(msg)
                        continue

                    publish_success = False
                    for attempt in range(1, 4):
                        delivery_err = []
                        def delivery_cb(err, msg):
                            if err is not None:
                                delivery_err.append(str(err))

                        try:
                            self.producer.produce(
                                SCORED_TOPIC,
                                key=sender.encode("utf-8") if sender else None,
                                value=payload,
                                callback=delivery_cb
                            )
                            remaining = self.producer.flush(timeout=5.0)
                            if remaining == 0 and len(delivery_err) == 0:
                                publish_success = True
                                break
                            else:
                                print(f"[Pipeline] Produce attempt {attempt} failed for txn {txn_id}: remaining={remaining}, errs={delivery_err}")
                                time.sleep(0.5)
                        except Exception as prod_err:
                            print(f"[Pipeline] Produce attempt {attempt} threw exception for txn {txn_id}: {prod_err}")
                            time.sleep(0.5)

                    if publish_success:
                        committed = self._commit_with_retry(msg, f"scored txn {txn_id}")
                        if committed:
                            print(f"[Pipeline] Scored txn {txn_id}: Status={scored['status']}, Score={scored['riskScore']}")
                    else:
                        print(f"[Pipeline] CRITICAL: Failed to publish scored event for txn {txn_id} after 3 attempts. Routing to DLQ...")
                        dlq_ok = self.send_to_dlq(raw_bytes, "Failed to publish scored event after 3 attempts")
                        if dlq_ok:
                            self._commit_with_retry(msg, f"dlq txn {txn_id}")
                        else:
                            print(f"[Pipeline] CRITICAL: DLQ delivery also failed for txn {txn_id}. Seeking back.")
                            self._seek_back(msg)
                except Exception as e:
                    if self.running:
                        print(f"[Pipeline] Consumer error: {e}. Reconnecting...")
                        time.sleep(2)
                        self._init_kafka()
        finally:
            if self.producer:
                try:
                    self.producer.flush(timeout=5.0)
                except Exception:
                    pass
            if self.consumer:
                try:
                    self.consumer.close()
                except Exception:
                    pass
