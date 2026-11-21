import time
import json
from typing import Tuple, List
import valkey

# Redis/Valkey key prefixes
VELOCITY_KEY_PREFIX = "upi:velocity:"
TRAVEL_KEY_PREFIX = "upi:travel:"
BASELINE_KEY_PREFIX = "upi:baseline:"

VELOCITY_WINDOW_SECONDS = 300  # 5 minutes sliding window
TRAVEL_EXPIRY_SECONDS = 900    # 15 minutes window
BASELINE_LIST_MAX_LEN = 10     # Last 10 transactions


def check_velocity(r: valkey.Valkey, sender_upi: str, current_time: float) -> Tuple[int, int, str]:
    """
    Sliding 5-minute window using Sorted Set.
    Count > 3 transactions in 5 mins -> +40 risk points.
    """
    key = f"{VELOCITY_KEY_PREFIX}{sender_upi}"
    cutoff = current_time - VELOCITY_WINDOW_SECONDS

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, "-inf", cutoff)
    member = f"{current_time}:{time.time_ns()}"
    pipe.zadd(key, {member: current_time})
    pipe.zcard(key)
    pipe.expire(key, VELOCITY_WINDOW_SECONDS + 60)
    results = pipe.execute()

    count = int(results[2])
    if count > 3:
        points = 40
        reason = f"High velocity: {count} transactions within 5 mins"
        return points, count, reason
    return 0, count, ""


def check_impossible_travel(r: valkey.Valkey, sender_upi: str, current_city: str, current_time: float) -> Tuple[int, str]:
    """
    Compare current city with last seen city for sender_upi within 15 minutes.
    If city changed -> +50 risk points.
    """
    key = f"{TRAVEL_KEY_PREFIX}{sender_upi}"
    val = r.get(key)
    points = 0
    reason = ""

    if val:
        try:
            data = json.loads(val.decode("utf-8") if isinstance(val, bytes) else val)
            last_city = data.get("city")
            last_time = float(data.get("time", current_time))
            time_diff_mins = max(0.1, round((current_time - last_time) / 60.0, 1))

            if last_city and last_city.lower().strip() != current_city.lower().strip():
                points = 50
                reason = f"Impossible travel: {last_city} to {current_city} in {time_diff_mins} mins"
        except Exception as e:
            print(f"[Rules] Error parsing last travel state: {e}")

    new_data = json.dumps({"city": current_city.strip(), "time": current_time})
    r.set(key, new_data, ex=TRAVEL_EXPIRY_SECONDS)
    return points, reason


def check_dynamic_user_baseline(r: valkey.Valkey, sender_upi: str, amount: float) -> Tuple[int, float, str]:
    """
    Rolling Average Amount of historical transactions.
    If amount > 5x user's historical rolling average -> +25 risk points.
    """
    key = f"{BASELINE_KEY_PREFIX}{sender_upi}"
    history_bytes = r.lrange(key, 0, BASELINE_LIST_MAX_LEN - 1)
    
    avg_amount = 0.0
    points = 0
    reason = ""

    if history_bytes and len(history_bytes) >= 2:
        amounts = [float(x.decode() if isinstance(x, bytes) else x) for x in history_bytes]
        avg_amount = sum(amounts) / len(amounts)

        if avg_amount > 0 and amount >= (avg_amount * 5.0) and amount >= 5000:
            points = 25
            ratio = round(amount / avg_amount, 1)
            reason = f"Baseline Anomaly: amount ₹{amount:,.0f} is {ratio}x user rolling average (₹{avg_amount:,.0f})"
    elif history_bytes:
        amounts = [float(x.decode() if isinstance(x, bytes) else x) for x in history_bytes]
        avg_amount = sum(amounts) / len(amounts)

    # Push current amount to user history list and cap at 10 items
    pipe = r.pipeline()
    pipe.lpush(key, str(amount))
    pipe.ltrim(key, 0, BASELINE_LIST_MAX_LEN - 1)
    pipe.expire(key, 86400 * 7)  # 7 days baseline memory
    pipe.execute()

    return points, round(avg_amount, 2), reason


def evaluate_transaction_risk(r: valkey.Valkey, ml_model, txn: dict) -> dict:
    """
    Explainable AI Hybrid Risk Engine:
    - Velocity Points (0 or 40)
    - Impossible Travel Points (0 or 50)
    - Dynamic Baseline Anomaly (0 or 25)
    - IsolationForest ML Score (0 to 30)
    
    Circuit Breaker: Total Score >= 75 -> FLAGGED, else APPROVED.
    """
    sender_upi = txn.get("senderUpi", "unknown")
    current_city = txn.get("city", "Unknown")
    amount = float(txn.get("amount", 0.0))
    current_time = time.time()

    reasons: List[str] = []

    # 1. Velocity Rule
    velocity_pts, freq_count, vel_reason = check_velocity(r, sender_upi, current_time)
    if vel_reason:
        reasons.append(vel_reason)

    # 2. Impossible Travel Rule
    travel_pts, travel_reason = check_impossible_travel(r, sender_upi, current_city, current_time)
    if travel_reason:
        reasons.append(travel_reason)

    # 3. Dynamic User Baseline Check
    baseline_pts, rolling_avg, baseline_reason = check_dynamic_user_baseline(r, sender_upi, amount)
    if baseline_reason:
        reasons.append(baseline_reason)

    # 4. ML Anomaly Model
    from model import compute_ml_risk_points
    ml_pts, raw_anomaly_score = compute_ml_risk_points(ml_model, amount, freq_count)
    if ml_pts >= 20:
        reasons.append(f"ML Outlier Alert: amount=₹{amount:,.2f}, anomaly_pts={ml_pts}")

    # High amount threshold safeguard
    if amount >= 50000 and ml_pts < 25:
        ml_pts = 30
        if not any("Outlier" in r for r in reasons):
            reasons.append(f"High-value transaction outlier: ₹{amount:,.2f}")

    total_score = min(100, velocity_pts + travel_pts + baseline_pts + ml_pts)
    status = "FLAGGED" if total_score >= 75 else "APPROVED"
    flag_reason = " | ".join(reasons) if reasons else "Normal transaction pattern"

    # Explainable AI Breakdown
    breakdown = {
        "velocityPoints": velocity_pts,
        "velocityCount5m": freq_count,
        "impossibleTravelPoints": travel_pts,
        "baselineAnomalyPoints": baseline_pts,
        "userRollingAverage": rolling_avg,
        "mlAnomalyPoints": ml_pts,
        "rawModelDecisionScore": round(raw_anomaly_score, 4)
    }

    return {
        "transactionId": txn.get("transactionId"),
        "senderUpi": sender_upi,
        "receiverUpi": txn.get("receiverUpi"),
        "amount": amount,
        "city": current_city,
        "deviceId": txn.get("deviceId"),
        "status": status,
        "riskScore": total_score,
        "flagReason": flag_reason,
        "scoreBreakdown": breakdown
    }
