"""Cell 3 — Operating-mode Clustering (KMeans) [SUPPORTING]"""

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
