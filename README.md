# Intelligent Hybrid Solar-Grid Charger

Capstone project — AIUB, Dept. of EEE, Group 07 (2026.2.7).
An edge-to-fog IoT charging system with rule-based safety, four-task on-device
ML, weather-informed scheduling, and a live web dashboard.

An ESP32 edge node reads the sensors, runs the hard safety rules, drives the
relays and MOSFETs, and streams telemetry to a Raspberry Pi fog node. The Pi
stores the data, runs the ML models, serves the dashboard, and pushes control
commands back to the ESP32.

---

## System architecture

```
   Sensors                ESP32 (edge)                 Raspberry Pi (fog)
   -------                ------------                 ------------------
  INA238 x2  ─┐        read + safety rules        Flask + SQLite backend
  INA237     ─┼─ I2C ─► drive relay / MOSFETs ─┐   REST API + dashboard
  DS18B20    ─┘         OLED status              │   4 ML models (joblib)
                                                 │   Open-Meteo scheduler
              POST JSON telemetry every 2 s ─────┘
              ◄──── control command in the POST response
```

Data path: ESP32 builds a 26-field JSON packet, POSTs it to `/api/data`, the
Pi validates and stores it, runs the ML models, and returns any queued
dashboard command in the response body. The ESP32 applies the command — but its
own safety layer (over-temp / over-voltage / low-SOC) always has the final say.

---

## Repository layout

```
solar-grid-charger/
├── firmware/Solar_AI_ESP32/   ESP32 Arduino firmware (modular .ino + .cpp/.h)
├── backend/                   Raspberry Pi Flask backend
│   ├── app.py                 REST API + dashboard routes
│   ├── database.py            SQLite (WAL), history windowing, event log
│   ├── ml_engine.py           loads + runs the 4 trained models per reading
│   ├── weather.py             Open-Meteo pre-charge advisory (cached)
│   ├── commands.py            whitelisted dashboard → ESP32 command queue
│   ├── validators.py          incoming-packet range checks
│   ├── serial_reader.py       optional UART bridge (ESP32 → Flask)
│   ├── templates/             dashboard.html goes here
│   └── Models_v2/             trained .pkl artefacts go here
├── ml/                        training pipeline
│   ├── notebooks/             solar_ml_pipeline.ipynb (run top to bottom)
│   ├── cells/                 the same 5 cells as standalone scripts
│   └── train_pipeline.py      flat single-file version
├── docs/                      capstone book, poster, IEEE paper
└── _archive/                  earlier backend drafts (kept for reference)
```

---

## Machine learning

Four tasks, trained on the logged operational dataset. Every design choice is
made explainable for the defense (baselines, leakage controls, validation
against untouched columns).

| Task | Model | Role | Notes |
|------|-------|------|-------|
| Operational anomaly detection | Isolation Forest | **primary** | `contamination=0.02`, 200 trees; validated by reboot-proximity lift |
| Operating-mode clustering | KMeans (k=4) | supporting | Solar-charge / Grid-charge / heavy-load / idle; validated vs `charging_source` and `load_level` |
| SOC trend prediction | Random Forest | secondary | Rising / Falling / Stable over the next window; time-based split, no leakage |
| Load-level classification | Random Forest | appendix | MOSFET-state features excluded on purpose (leakage demo included) |

Training lives in `ml/`; inference lives in `backend/ml_engine.py`, which
rebuilds the rolling / lag / time-of-day features from a short history buffer
so the ESP32 firmware never has to change.

---

## Hardware

| Part | Detail |
|------|--------|
| Edge MCU | ESP32 Dev Module |
| Fog node | Raspberry Pi (Flask + SQLite) |
| Current/voltage | INA238 ×2 (0x40, 0x41) + INA237 (0x44), R015 shunts, I2C @ 50 kHz |
| Temperature | DS18B20 (1-Wire, 4.7 k pull-up) |
| Display | SSD1309 128×64 OLED (SPI, U8g2) |
| Switching | opto-isolated AC relay + D4184 MOSFETs ×3 (loads) |
| Charging | 20 A MPPT, 100 W panel |
| Battery | 12 V 30 Ah LiFePO4 |

Pins, I2C addresses, and all thresholds live in
`firmware/Solar_AI_ESP32/config.h`.

---

## Getting started

### Firmware (Arduino IDE)

1. Open `firmware/Solar_AI_ESP32/Solar_AI_ESP32.ino` (all tabs load together).
2. In `config.h`, set `WIFI_SSID` / `WIFI_PASS` and the Pi hostname.
   The committed values are placeholders — do **not** commit your real
   credentials (see the note below).
3. Libraries: INA238 (Rob Tillaart), OneWire, DallasTemperature, U8g2,
   ArduinoJson.
4. Board: ESP32 Dev Module → Upload.

### Backend (Raspberry Pi)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 reset_database.py     # first run only: creates the SQLite schema
python3 app.py                # http://<pi-host>:5000
```

Put the trained `.pkl` files in `backend/Models_v2/` and `dashboard.html` in
`backend/templates/` before starting, or the ML/dashboard features stay off
(the API still runs).

### ML training

Open `ml/notebooks/solar_ml_pipeline.ipynb` on Kaggle (or run
`ml/train_pipeline.py`) with the dataset in place, run all cells, then copy the
saved `.pkl` files into `backend/Models_v2/`.

---

## A note on credentials

`config.h` is committed with placeholder WiFi credentials. After you enter your
real SSID/password locally, keep them out of git with:

```bash
git update-index --skip-worktree firmware/Solar_AI_ESP32/config.h
```

That stops your local edit from being staged. `.gitignore` also blocks
`config.local.h`, `secrets.h`, and `.env` if you prefer to keep secrets in a
separate uncommitted file.

---

## Group 07

Shah MD Atikur Rahman · Tafhim Ahmed · MD Afrahim Islam · MD Muntasir Ul Islam
Supervisor: Abu Hena Muhammad Shatil, Associate Professor, Dept. of EEE, AIUB.
