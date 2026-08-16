"""Cell 5 — Load-level Classification [APPENDIX / leakage demonstration]"""

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
