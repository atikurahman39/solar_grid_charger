"""
Solar-Grid Charger — full ML training pipeline (flat script version).
Mirror of notebooks/solar_ml_pipeline.ipynb; run on Kaggle or locally
with the logged dataset present at PATH (see Cell 1).
"""

# ======================================================================
# CELL 1 — Load, Clean, Feature Engineering
# ======================================================================
import pandas as pd
import numpy as np

# ---- 1. LOAD ----
PATH = '/kaggle/input/datasets/atikurrahman21/solar-data/solar_data_raw.csv'
df = pd.read_csv(PATH, low_memory=False)   # low_memory=False: charging_source has mixed types
print(f"Loaded: {df.shape[0]:,} rows, {df.shape[1]} columns")

# ---- 2. CLEAN ----
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.sort_values('timestamp').reset_index(drop=True)
df['charging_source'] = df['charging_source'].fillna('None')   # NaN = no charging = valid 'None' state

before = len(df)
df = df.drop_duplicates(subset='timestamp', keep='first').reset_index(drop=True)
print(f"Dropped {before - len(df):,} duplicate timestamps")

# battery_current == load_current (no battery-side sensor), battery_power == -load_power,
# relay_state == constant 1 (zero variance)
drop_cols = ['battery_current', 'battery_power', 'relay_state']
df = df.drop(columns=[c for c in drop_cols if c in df.columns])
print(f"Dropped broken columns: {drop_cols}")

# ---- 3. SEGMENT (split at reboots and big gaps so rolling/lag never cross a discontinuity) ----
gap    = df['timestamp'].diff().dt.total_seconds()
reboot = df['uptime_s'].diff() < 0
new_segment = (gap > 300) | reboot
new_segment.iloc[0] = True
df['segment_id'] = new_segment.cumsum()
print(f"Data split into {df['segment_id'].nunique()} clean segments "
      f"({reboot.sum()} reboots, {(gap>300).sum()} big gaps)")

# ---- 4. FEATURE ENGINEERING (reusable function, also used on the Pi at deploy time) ----
PV_EFF = 0.90   # ASSUMED conversion efficiency (typical MPPT value); NOT measured on this system

def engineer_features(g):
    g = g.copy()
    # cyclical time: 23h and 0h are adjacent, so encode as sin/cos
    h = g['timestamp'].dt.hour + g['timestamp'].dt.minute / 60.0
    g['hour_sin'] = np.sin(2 * np.pi * h / 24)
    g['hour_cos'] = np.cos(2 * np.pi * h / 24)
    # physics-based net battery current (battery_current column is broken)
    # I_batt = (eta*P_solar + eta*P_charge - P_load) / V_batt , eta assumed 0.90
    g['ibatt_est'] = (PV_EFF * g['solar_power'] + PV_EFF * g['charge_power']
                      - g['load_power']) / g['battery_voltage'].replace(0, np.nan)
    g['ibatt_est'] = g['ibatt_est'].fillna(0)
    # rolling mean/std (window 30 = 60s, 150 = 300s @ 2s interval)
    for col in ['battery_voltage', 'load_current', 'solar_power', 'soc']:
        g[f'{col}_rmean60']  = g[col].rolling(30, min_periods=1).mean()
        g[f'{col}_rstd60']   = g[col].rolling(30, min_periods=1).std().fillna(0)
        g[f'{col}_rmean300'] = g[col].rolling(150, min_periods=1).mean()
    # lag + rate-of-change
    for col in ['battery_voltage', 'soc', 'load_current']:
        g[f'{col}_lag30']  = g[col].shift(30)
        g[f'{col}_diff60'] = g[col] - g[f'{col}_lag30']
    g['soc_slope300'] = g['soc'] - g['soc'].shift(150)
    return g

# preserve segment_id across all pandas versions (newer ones drop grouping col in apply)
seg = df['segment_id'].copy()
df = df.groupby('segment_id', group_keys=False).apply(engineer_features).reset_index(drop=True)
if 'segment_id' not in df.columns:
    df['segment_id'] = seg.values

# ---- 5. SUMMARY ----
print("charging_source:", df['charging_source'].value_counts().to_dict())
print("segments:", df['segment_id'].nunique())
df.head()


# ======================================================================
# CELL 2 — Operational Anomaly Detection (Isolation Forest) [PRIMARY]
# ======================================================================
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


# ======================================================================
# CELL 3 — Operating-mode Clustering (KMeans) [SUPPORTING]
# ======================================================================
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import joblib

# power flows + battery state define an operating MODE.
# DELIBERATELY exclude charging_source / load_level -> used later to VALIDATE the clusters.
CLUSTER_FEATURES = ['solar_power', 'load_power', 'charge_power',
                    'battery_voltage', 'ibatt_est']
work = df.dropna(subset=CLUSTER_FEATURES).copy()

X = work[CLUSTER_FEATURES].values
scaler = StandardScaler().fit(X)      # KMeans is distance-based -> scaling REQUIRED
Xs = scaler.transform(X)

# --- k selection: elbow (inertia) + silhouette (on 20k sample for speed) ---
rng = np.random.RandomState(42)
idx = rng.choice(len(Xs), 20000, replace=False)
print(f"{'k':>3} {'inertia':>10} {'silhouette':>11}")
for k in range(2, 7):
    km_ = KMeans(k, n_init=10, random_state=42).fit(Xs)
    sil = silhouette_score(Xs[idx], km_.predict(Xs[idx]))
    print(f"{k:>3} {km_.inertia_:>10.0f} {sil:>11.3f}")

# --- final model: k=4 ---
# NOTE: silhouette is nearly flat (~0.40-0.45) across k, so it is NOT decisive here;
# k=4 is chosen from the 4 physical operating modes + elbow, then VALIDATED below.
k = 4
km = KMeans(k, n_init=10, random_state=42).fit(Xs)
work['cluster'] = km.labels_
print("\ncluster sizes:", np.bincount(work['cluster']).tolist())

print("\ncluster profiles (mean raw features):")
print(work.groupby('cluster')[CLUSTER_FEATURES].mean().round(2).to_string())

# --- VALIDATION vs untouched columns (the real justification for k=4) ---
print("\nVALIDATION vs charging_source (row-normalized):")
print(pd.crosstab(work['cluster'], work['charging_source'],
                  normalize='index').round(2).to_string())
print("\nVALIDATION vs load_level (mean per cluster):")
print(work.groupby('cluster')['load_level'].mean().round(2).to_string())

# --- name clusters (verify against profiles above) ---
CLUSTER_NAMES = {0: 'Solar-charge', 1: 'Discharge/heavy-load',
                 2: 'Grid-charge', 3: 'Idle/light'}
print("\nnamed:", CLUSTER_NAMES)

# --- SAVE ---
joblib.dump(km,               'cluster_model.pkl')
joblib.dump(scaler,           'cluster_scaler.pkl')
joblib.dump(CLUSTER_FEATURES, 'cluster_features.pkl')
joblib.dump(CLUSTER_NAMES,    'cluster_names.pkl')
print("\nSaved: cluster_model.pkl, cluster_scaler.pkl, cluster_features.pkl, cluster_names.pkl")


# ======================================================================
# CELL 4 — Battery Operating Trend Prediction (Random Forest) [SECONDARY]
# ======================================================================
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
import joblib

# safety: ensure segment_id exists
if 'segment_id' not in df.columns:
    gap = df['timestamp'].diff().dt.total_seconds(); rb = df['uptime_s'].diff() < 0
    ns = (gap > 300) | rb; ns.iloc[0] = True; df['segment_id'] = ns.cumsum()

# --- FORWARD target: SOC change over NEXT 5 min (150 rows), per segment ---
# NOTE: target is derived from firmware Coulomb-counting SOC, treated as the system's
# OPERATIONAL REFERENCE (not absolute electrochemical ground truth). No leakage:
# target is a FUTURE value; all features are from the PRESENT.
df['soc_future']     = df.groupby('segment_id')['soc'].shift(-150)
df['soc_change_fut'] = df['soc_future'] - df['soc']

def label_trend(x):
    if x >  1: return 'Rising'     # +/-1% threshold ignores sensor noise
    if x < -1: return 'Falling'
    return 'Stable'
df['trend'] = df['soc_change_fut'].apply(lambda x: label_trend(x) if pd.notna(x) else np.nan)

TREND_FEATURES = ['battery_voltage','soc','solar_power','load_power','ibatt_est',
    'load_current','battery_temperature','hour_sin','hour_cos','soc_diff60',
    'battery_voltage_diff60','soc_rmean300','load_current_rmean60','charge_power']
work = df.dropna(subset=TREND_FEATURES + ['trend']).copy()
print("rows used:", len(work), "| label balance:", work['trend'].value_counts().to_dict())

# --- TIME-BASED split (earlier 70% train, later 30% test) -> no leakage ---
cut = work['timestamp'].quantile(0.7)
tr = work[work['timestamp'] <  cut]
te = work[work['timestamp'] >= cut]
print(f"train={len(tr):,}  test={len(te):,}")

# --- BASELINE COMPARISON (proves RF is justified) ---
sc = StandardScaler().fit(tr[TREND_FEATURES])        # LogReg needs scaling
Xtr, Xte = sc.transform(tr[TREND_FEATURES]), sc.transform(te[TREND_FEATURES])
print("\n=== BASELINE COMPARISON ===")
baselines = {
    'Majority (Dummy)': (DummyClassifier(strategy='most_frequent'), False),
    'Logistic Reg':     (LogisticRegression(max_iter=1000, n_jobs=-1), True),
    'Decision Tree':    (DecisionTreeClassifier(max_depth=8, random_state=42), False),
    'Random Forest':    (RandomForestClassifier(n_estimators=120, max_depth=16,
                          min_samples_leaf=5, n_jobs=-1, random_state=42,
                          class_weight='balanced'), False),
}
final_rf = None
for name, (m, scale) in baselines.items():
    if scale: m.fit(Xtr, tr['trend']); p = m.predict(Xte)
    else:     m.fit(tr[TREND_FEATURES], tr['trend']); p = m.predict(te[TREND_FEATURES])
    print(f"  {name:18s} acc={accuracy_score(te['trend'],p):.3f}  "
          f"f1_macro={f1_score(te['trend'],p,average='macro'):.3f}")
    if name == 'Random Forest': final_rf = m

# --- PER-CLASS metrics (the important part for a battery system) ---
pred = final_rf.predict(te[TREND_FEATURES])
print("\n=== PER-CLASS METRICS (Random Forest) ===")
print(classification_report(te['trend'], pred, digits=3))
print("confusion [rows=true, cols=pred] order [Falling,Rising,Stable]:")
print(confusion_matrix(te['trend'], pred, labels=['Falling','Rising','Stable']))
print("\ntop features:")
print(pd.Series(final_rf.feature_importances_, index=TREND_FEATURES)
      .sort_values(ascending=False).head(6).round(3).to_string())

# --- SAVE ---
joblib.dump(final_rf,        'trend_model.pkl')
joblib.dump(TREND_FEATURES,  'trend_features.pkl')
print("\nSaved: trend_model.pkl, trend_features.pkl")


# ======================================================================
# CELL 5 — Load-level Classification [APPENDIX / leakage demonstration]
# ======================================================================
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
import joblib

# CRITICAL: exclude mosfet states. load_level is DERIVED from them,
# so including them makes the task circular (trivially near-perfect).
LOAD_FEATURES = ['load_current', 'load_power', 'battery_voltage', 'solar_power',
                 'ibatt_est', 'hour_sin', 'hour_cos',
                 'load_current_rmean60', 'load_current_rstd60']

df['mosfet_sum'] = df.mosfet1_state + df.mosfet2_state + df.mosfet3_state  # only to demo the trap

work = df.dropna(subset=LOAD_FEATURES).copy()
cut = work['timestamp'].quantile(0.7)
tr = work[work['timestamp'] <  cut]
te = work[work['timestamp'] >= cut]
print(f"train={len(tr):,}  test={len(te):,}")

# --- HONEST model (no mosfet leakage) ---
clf = RandomForestClassifier(n_estimators=120, max_depth=16, min_samples_leaf=5,
                             n_jobs=-1, random_state=42, class_weight='balanced')
clf.fit(tr[LOAD_FEATURES], tr['load_level'])
pred = clf.predict(te[LOAD_FEATURES])
print("[HONEST] acc:", round(accuracy_score(te['load_level'], pred), 3),
      " f1_macro:", round(f1_score(te['load_level'], pred, average='macro'), 3))

# --- DEMONSTRATE THE TRAP: adding mosfet_sum trivializes it ---
clf2 = RandomForestClassifier(n_estimators=50, max_depth=10, n_jobs=-1, random_state=42)
clf2.fit(tr[LOAD_FEATURES + ['mosfet_sum']], tr['load_level'])
pred2 = clf2.predict(te[LOAD_FEATURES + ['mosfet_sum']])
print("[LEAKY]  acc:", round(accuracy_score(te['load_level'], pred2), 3),
      "  <- trivial; this is WHY we exclude mosfet states")

# --- SAVE ---
joblib.dump(clf,           'load_model.pkl')
joblib.dump(LOAD_FEATURES,  'load_features.pkl')
print("\nSaved: load_model.pkl, load_features.pkl")


