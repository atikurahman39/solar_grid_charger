"""Cell 4 — Battery Operating Trend Prediction (Random Forest) [SECONDARY]"""

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
