# ML pipeline

Four-task edge-ML pipeline. Train here, deploy the artefacts in
`../backend/Models_v2/`.

- `notebooks/solar_ml_pipeline.ipynb` — run top to bottom (Kaggle-ready)
- `cells/` — the same 5 cells as standalone scripts
- `train_pipeline.py` — flat single-file version
- `models/` — trained `.pkl` output (gitignored by default)

| Cell | Task | Model |
|------|------|-------|
| 1 | Load / clean / feature engineering | — |
| 2 | Anomaly detection | Isolation Forest (primary) |
| 3 | Operating-mode clustering | KMeans k=4 |
| 4 | SOC trend prediction | Random Forest |
| 5 | Load-level classification | Random Forest (leakage demo) |

Each cell prints its own validation/baseline output and saves its model with
`joblib`, so every choice is explainable at the defense.
