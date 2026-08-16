# Backend (Raspberry Pi fog node)

Flask + SQLite service that ingests ESP32 telemetry, runs the ML models,
serves the dashboard, and relays control commands back to the ESP32.

## Run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 reset_database.py   # first run: create schema
python3 app.py              # or ./start.sh
```

## API

| Method + path | Purpose |
|---------------|---------|
| `POST /api/data` | ESP32 pushes a telemetry packet; response carries any queued command |
| `GET /api/latest` | newest sensor row |
| `GET /api/history?hours=6` | windowed history, downsampled to ~360 points |
| `GET /api/ml` | latest anomaly / cluster / trend / load result |
| `GET /api/weather` | Open-Meteo pre-charge advisory |
| `GET/POST /api/command` | view / queue a whitelisted control command |
| `GET /api/status`, `/health` | diagnostics |
| `GET /download/csv` | export the log as CSV |

## Files

`app.py` routes · `database.py` storage + event log · `ml_engine.py` inference ·
`weather.py` scheduler · `commands.py` command queue · `validators.py` range
checks · `config.py` paths/ports · `serial_reader.py` optional UART bridge ·
`reset_database.py` / `test_db.py` helpers.

Trained models load from `Models_v2/`; the dashboard renders from
`templates/dashboard.html`.
