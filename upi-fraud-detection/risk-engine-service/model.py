import os
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

MODEL_FILE = os.path.join(os.path.dirname(__file__), "model.joblib")


def generate_synthetic_data(n_normal: int = 2500, n_anomalous: int = 150):
    """
    Generate synthetic UPI transaction features:
    Feature 1: amount (INR)
    Feature 2: frequency_5m (transactions count in sliding 5 mins)
    """
    np.random.seed(42)

    # Normal UPI traffic:
    # 80% micropayments (tea, groceries, cab, food: Rs. 10 to Rs. 800)
    normal_micro = np.random.exponential(scale=150, size=int(n_normal * 0.8)) + 10
    # 20% moderate bill payments / shopping (Rs. 800 to Rs. 5,000)
    normal_mod = np.random.uniform(800, 5000, size=int(n_normal * 0.2))
    normal_amounts = np.concatenate([normal_micro, normal_mod])
    normal_freq = np.random.choice([1, 2, 3], size=n_normal, p=[0.75, 0.20, 0.05])

    normal_features = np.column_stack((normal_amounts, normal_freq))

    # Anomalies:
    # High-value outliers (Rs. 40,000 to Rs. 100,000) or high velocity (4 to 12 in 5m)
    anomaly_amounts = np.random.uniform(40000, 100000, size=n_anomalous)
    anomaly_freq = np.random.randint(4, 15, size=n_anomalous)
    anomaly_features = np.column_stack((anomaly_amounts, anomaly_freq))

    X = np.vstack([normal_features, anomaly_features])
    return X


def train_and_save_model(model_path: str = MODEL_FILE) -> IsolationForest:
    print("[Model] Generating synthetic UPI training dataset...")
    X = generate_synthetic_data()

    print(f"[Model] Training IsolationForest with {len(X)} samples...")
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X)

    joblib.dump(model, model_path)
    print(f"[Model] Model successfully saved to {model_path}")
    return model


def get_or_load_model(model_path: str = MODEL_FILE) -> IsolationForest:
    if os.path.exists(model_path):
        try:
            return joblib.load(model_path)
        except Exception as e:
            print(f"[Model] Failed to load existing model ({e}). Re-training...")
    return train_and_save_model(model_path)


def compute_ml_risk_points(model: IsolationForest, amount: float, frequency_5m: int) -> tuple[int, float]:
    """
    Predict anomaly score using IsolationForest.
    decision_function: higher = normal, lower/negative = anomalous.
    Map negative/low scores to 0-30 risk points.
    """
    features = np.array([[float(amount), float(frequency_5m)]])
    # decision_function returns float roughly between -0.35 and 0.25
    raw_score = float(model.decision_function(features)[0])
    is_outlier = int(model.predict(features)[0]) == -1

    # Normalization:
    # If decision_function <= -0.15 -> full 30 pts
    # If decision_function >= 0.15 -> 0 pts
    # Linear scale between -0.15 and 0.15
    if raw_score <= -0.15 or amount >= 50000:
        risk_points = 30
    elif raw_score >= 0.12:
        risk_points = 0
    else:
        # Scale range [-0.15, 0.12] to [30, 0]
        norm = (raw_score - (-0.15)) / (0.12 - (-0.15))
        risk_points = int(round((1.0 - norm) * 30))
        risk_points = max(0, min(30, risk_points))

    # Outlier override guarantees at least 20 points
    if is_outlier and risk_points < 20:
        risk_points = 20

    return risk_points, raw_score
