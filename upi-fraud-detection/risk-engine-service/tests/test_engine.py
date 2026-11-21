import pytest
import fakeredis
from model import generate_synthetic_data, train_and_save_model, compute_ml_risk_points
from rules import (
    check_velocity,
    check_impossible_travel,
    check_dynamic_user_baseline,
    evaluate_transaction_risk
)


def test_synthetic_data_shape():
    X = generate_synthetic_data(n_normal=100, n_anomalous=20)
    assert X.shape == (120, 2)
    assert (X[:, 0] > 0).all()


def test_velocity_rule_trigger():
    """Verify velocity rule: 4th transaction within 5 minutes triggers exactly +40 risk points"""
    r = fakeredis.FakeRedis()
    sender = "testuser@okaxis"
    now = 1000.0

    # 1st, 2nd, 3rd transactions within 5m
    for i in range(1, 4):
        pts, count, reason = check_velocity(r, sender, now + (i * 10))
        assert pts == 0
        assert count == i
        assert reason == ""

    # 4th transaction within 5m
    pts, count, reason = check_velocity(r, sender, now + 40)
    assert pts == 40
    assert count == 4
    assert "High velocity: 4 transactions" in reason


def test_impossible_travel_trigger():
    """Verify impossible travel: city changed within 15 minutes adds +50 points"""
    r = fakeredis.FakeRedis()
    sender = "traveler@okhdfc"
    now = 5000.0

    # 1. First transaction in Bengaluru
    pts, reason = check_impossible_travel(r, sender, "Bengaluru", now)
    assert pts == 0
    assert reason == ""

    # 2. Second transaction in Bengaluru 60s later (Same city)
    pts, reason = check_impossible_travel(r, sender, "Bengaluru", now + 60)
    assert pts == 0
    assert reason == ""

    # 3. Third transaction in Delhi 120s later (City change)
    pts, reason = check_impossible_travel(r, sender, "Delhi", now + 120)
    assert pts == 50
    assert "Impossible travel: Bengaluru to Delhi" in reason


def test_dynamic_user_baseline_profiling():
    """Verify dynamic baseline: transaction > 5x user rolling average adds +25 points"""
    r = fakeredis.FakeRedis()
    sender = "retail_buyer@oksbi"

    # User normally spends Rs 200, Rs 300, Rs 250 (avg: 250)
    check_dynamic_user_baseline(r, sender, 200.0)
    check_dynamic_user_baseline(r, sender, 300.0)
    pts, avg, reason = check_dynamic_user_baseline(r, sender, 250.0)
    assert pts == 0
    assert avg == 250.0

    # Suddenly spends Rs 15,000 (60x rolling average)
    pts_anomaly, avg_new, reason_anomaly = check_dynamic_user_baseline(r, sender, 15000.0)
    assert pts_anomaly == 25
    assert "Baseline Anomaly" in reason_anomaly


def test_circuit_breaker_boundary(tmp_path):
    """
    Exact boundary test:
    Total risk score < 75 -> APPROVED
    Total risk score >= 75 -> FLAGGED
    """
    model_path = str(tmp_path / "test_model.joblib")
    model = train_and_save_model(model_path)
    r = fakeredis.FakeRedis()

    # Normal transaction: Score = 0 -> APPROVED
    normal_txn = {
        "transactionId": "11111111-1111-1111-1111-111111111111",
        "senderUpi": "normal@okaxis",
        "receiverUpi": "merchant@icici",
        "amount": 250.0,
        "city": "Mumbai",
        "deviceId": "dev-01"
    }
    res_normal = evaluate_transaction_risk(r, model, normal_txn)
    assert res_normal["status"] == "APPROVED"
    assert res_normal["riskScore"] < 75
    assert "scoreBreakdown" in res_normal

    # High Value + Impossible Travel: Score = 30 + 50 = 80 (>= 75) -> FLAGGED
    fraud_txn = {
        "transactionId": "22222222-2222-2222-2222-222222222222",
        "senderUpi": "normal@okaxis",  # City changes Mumbai -> Delhi
        "receiverUpi": "mule@icici",
        "amount": 95000.0,
        "city": "Delhi",
        "deviceId": "dev-02"
    }
    res_fraud = evaluate_transaction_risk(r, model, fraud_txn)
    assert res_fraud["status"] == "FLAGGED"
    assert res_fraud["riskScore"] >= 75
    assert res_fraud["scoreBreakdown"]["impossibleTravelPoints"] == 50
    assert res_fraud["scoreBreakdown"]["mlAnomalyPoints"] >= 20
