# Dashboard template

`app.py` renders `dashboard.html` from this folder.

Drop the final panel-based dashboard here:

```
templates/
└── dashboard.html      ← Grafana/SCADA-inspired panel layout
static/                 ← any CSS / JS / Chart.js assets
```

The dashboard polls these endpoints:
- `GET /api/latest`   — newest sensor row
- `GET /api/history`  — last 6 h, downsampled to ~360 points
- `GET /api/ml`       — latest anomaly / cluster / trend / load result
- `GET /api/weather`  — Open-Meteo pre-charge advisory
- `POST /api/command` — queue a whitelisted control command
