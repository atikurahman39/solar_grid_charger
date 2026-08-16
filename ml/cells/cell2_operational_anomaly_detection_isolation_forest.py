"""Cell 2 — Operational Anomaly Detection (Isolation Forest) [PRIMARY]"""

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

# raw signals + volatility/rate features that expose abnormal behavior
ANOMALY_FEATURES = [
    'battery_voltage', 'battery_temperature', 'soc',
    'solar_power', 'load_power', 'ibatt_est',
    'battery_voltage_rstd60', 'load_current_rstd60',
    'soc_diff60', 'battery_voltage_diff60',
]
work = df.dropna(subset=ANOMALY_FEATURES).copy()
print("rows used:", len(work))

X = work[ANOMALY_FEATURES].values
scaler = StandardScaler().fit(X)
Xs = scaler.transform(X)

# --- final model ---
iso = IsolationForest(n_estimators=200, contamination=0.02, random_state=42, n_jobs=-1)
work['anomaly']       = iso.fit_predict(Xs)      # -1 = anomaly, 1 = normal
work['anomaly_score'] = iso.score_samples(Xs)
n_anom = (work['anomaly'] == -1).sum()
print(f"flagged anomalies: {n_anom:,} ({100*n_anom/len(work):.2f}%)")

# --- reboot-proximity mask (our only real 'event' ground truth) ---
pos = {ix: i for i, ix in enumerate(work.index)}
near = np.zeros(len(work), dtype=bool)
for ix in work.index[work['uptime_s'].diff() < 0]:
    i = pos.get(ix)
    if i is not None:
        near[max(0, i-15):i+15] = True
work['near_reboot'] = near

ar_near = (work.loc[work.near_reboot,  'anomaly'] == -1).mean()
ar_far  = (work.loc[~work.near_reboot, 'anomaly'] == -1).mean()
print(f"\nVALIDATION @ contamination=0.02:")
print(f"  anomaly rate NEAR reboots : {ar_near:.3f}")
print(f"  anomaly rate elsewhere    : {ar_far:.3f}")
print(f"  lift: {ar_near/max(ar_far,1e-9):.1f}x")

# --- ROBUSTNESS: contamination sensitivity (proves the lift is not cherry-picked) ---
print("\nCONTAMINATION SENSITIVITY:")
print(f"  {'contam':>7} {'anom%':>7} {'lift':>7}")
for c in [0.01, 0.02, 0.03, 0.05]:
    lab = IsolationForest(n_estimators=200, contamination=c,
                          random_state=42, n_jobs=-1).fit_predict(Xs)
    lift = (lab[near]==-1).mean() / max((lab[~near]==-1).mean(), 1e-9)
    print(f"  {c:>7} {100*(lab==-1).mean():>6.1f}% {lift:>6.1f}x")

# --- what drives anomalies ---
anom, norm = work[work.anomaly==-1], work[work.anomaly==1]
print("\nfeature means (anomaly vs normal):")
for f in ['battery_voltage_rstd60', 'soc_diff60', 'ibatt_est', 'battery_temperature']:
    print(f"  {f:26s} anom={anom[f].mean():8.3f}  normal={norm[f].mean():8.3f}")

# --- SAVE ---
joblib.dump(iso, 'anomaly_model.pkl')
joblib.dump(scaler, 'anomaly_scaler.pkl')
joblib.dump(ANOMALY_FEATURES, 'anomaly_features.pkl')
print("\nSaved: anomaly_model.pkl, anomaly_scaler.pkl, anomaly_features.pkl")
