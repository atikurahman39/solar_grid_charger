"""
ml_engine.py  -  runs the four trained models on the Pi.

The ESP32 firmware does NOT change. It keeps sending the same 26-field JSON.
This module keeps a short rolling history of those readings so it can rebuild
the derived features the models were trained on (rolling std/mean, diffs,
time-of-day, estimated battery current), then runs:

    anomaly  -> IsolationForest   -> normal / ANOMALY  + score
    cluster  -> KMeans            -> operating regime name
    load     -> RandomForest      -> predicted load level (0-7)
    trend    -> RandomForest      -> SOC trend: Rising / Falling / Stable

Call ml_predict(row_dict) once per incoming reading; it returns a dict you can
store and show on the dashboard.
"""

import os
import math
import warnings
from collections import deque
from datetime import datetime

import numpy as np
import joblib

warnings.filterwarnings("ignore")   # silence sklearn version-mismatch notes

MODEL_DIR = os.path.join(os.path.dirname(__file__), "Models_v2")

# ---- load everything once at import ----
def _load(name):
    return joblib.load(os.path.join(MODEL_DIR, name))

anomaly_model    = _load("anomaly_model.pkl")
anomaly_scaler   = _load("anomaly_scaler.pkl")
anomaly_features = _load("anomaly_features.pkl")

cluster_model    = _load("cluster_model.pkl")
cluster_scaler   = _load("cluster_scaler.pkl")
cluster_features = _load("cluster_features.pkl")
cluster_names    = _load("cluster_names.pkl")

load_model       = _load("load_model.pkl")
load_features    = _load("load_features.pkl")

trend_model      = _load("trend_model.pkl")
trend_features   = _load("trend_features.pkl")

# ---- rolling history for the derived features ----
# 300 samples covers the longest window any model needs (soc_rmean300).
HISTORY = deque(maxlen=300)


def _rstd(key, n):
    vals = [h[key] for h in list(HISTORY)[-n:] if h.get(key) is not None]
    return float(np.std(vals)) if len(vals) >= 2 else 0.0


def _rmean(key, n):
    vals = [h[key] for h in list(HISTORY)[-n:] if h.get(key) is not None]
    return float(np.mean(vals)) if vals else 0.0


def _diff(key, n):
    hist = list(HISTORY)
    if len(hist) <= n:
        return 0.0
    now = hist[-1].get(key)
    past = hist[-1 - n].get(key)
    if now is None or past is None:
        return 0.0
    return float(now - past)


def _build_features(row):
    """Turn one raw reading (+ the rolling history) into every feature the
    models expect, keyed by name."""

    f = {}

    # --- straight from the JSON ---
    for k in ("battery_voltage", "battery_temperature", "soc", "solar_power",
              "load_power", "load_current", "charge_power"):
        f[k] = float(row.get(k, 0) or 0)

    # --- estimated battery current ---
    # Positive while charging, negative while discharging. charge_current is the
    # measured total into the battery; load_current is what is leaving it.
    charge_c = float(row.get("charge_current", 0) or 0)
    load_c   = float(row.get("load_current", 0) or 0)
    f["ibatt_est"] = charge_c - load_c

    # --- time of day, cyclic ---
    ts = row.get("timestamp")
    try:
        hour = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").hour \
            if ts else datetime.now().hour
    except Exception:
        hour = datetime.now().hour
    f["hour_sin"] = math.sin(2 * math.pi * hour / 24)
    f["hour_cos"] = math.cos(2 * math.pi * hour / 24)

    # the current reading must be in history before we compute rolling stats
    snapshot = dict(f)
    snapshot["load_current"] = load_c
    HISTORY.append(snapshot)

    # --- rolling / diff features ---
    f["battery_voltage_rstd60"] = _rstd("battery_voltage", 60)
    f["load_current_rstd60"]    = _rstd("load_current", 60)
    f["load_current_rmean60"]   = _rmean("load_current", 60)
    f["soc_rmean300"]           = _rmean("soc", 300)
    f["soc_diff60"]             = _diff("soc", 60)
    f["battery_voltage_diff60"] = _diff("battery_voltage", 60)

    return f


def _vector(feature_dict, feature_list):
    return np.array([[feature_dict.get(name, 0.0) for name in feature_list]])


def ml_predict(row):
    """Run all four models on one reading. Returns a dict of results."""

    f = _build_features(row)
    result = {}

    # ---- anomaly ----
    Xa = anomaly_scaler.transform(_vector(f, anomaly_features))
    is_anom = int(anomaly_model.predict(Xa)[0])          # -1 anomaly, 1 normal
    result["anomaly"] = (is_anom == -1)
    result["anomaly_score"] = round(float(anomaly_model.decision_function(Xa)[0]), 4)

    # ---- operating cluster ----
    Xc = cluster_scaler.transform(_vector(f, cluster_features))
    cid = int(cluster_model.predict(Xc)[0])
    result["cluster_id"] = cid
    result["cluster_name"] = cluster_names.get(cid, str(cid))

    # ---- predicted load level ----
    Xl = _vector(f, load_features)
    result["predicted_load_level"] = int(load_model.predict(Xl)[0])

    # ---- SOC trend ----
    Xt = _vector(f, trend_features)
    result["soc_trend"] = str(trend_model.predict(Xt)[0])

    # warming up: rolling features need history to be meaningful
    result["ml_warm"] = len(HISTORY) >= 60

    return result


if __name__ == "__main__":
    # quick self-test
    demo = {
        "timestamp": "2026-07-26 14:30:00",
        "battery_voltage": 13.2, "battery_temperature": 30.0, "soc": 58.5,
        "solar_power": 3.4, "load_power": 18.0, "load_current": 1.4,
        "charge_power": 0.0, "charge_current": 0.2,
    }
    for i in range(65):          # feed a few so rolling features warm up
        r = ml_predict(demo)
    print("Self-test output:")
    for k, v in r.items():
        print(f"  {k}: {v}")
