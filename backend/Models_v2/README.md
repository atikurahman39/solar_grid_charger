# Trained model artefacts

`ml_engine.py` loads these at startup. They are produced by the ML pipeline
in `../../ml/` (see each training cell's `joblib.dump(...)` calls).

Expected files:

```
anomaly_model.pkl      anomaly_scaler.pkl      anomaly_features.pkl
cluster_model.pkl      cluster_scaler.pkl      cluster_features.pkl   cluster_names.pkl
trend_model.pkl        trend_features.pkl
load_model.pkl         load_features.pkl
```

`.pkl` files are gitignored by default (they are regenerable binaries).
To version them anyway, remove the `Models_v2/*.pkl` line from `.gitignore`,
or track them with Git LFS.
