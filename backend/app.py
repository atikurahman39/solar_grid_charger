from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime

from config import HOST, PORT, DEBUG

from database import (
    create_database,
    insert_data,
    get_latest_data,
    get_history,
    get_history_window,
    create_events_table,
    log_event,
    get_events,
    get_unseen_count,
    mark_events_seen,
    get_total_records,
    export_csv
)

from validators import validate_data

# ML inference engine (loads the 4 trained models once at startup)
try:
    from ml_engine import ml_predict
    ML_ENABLED = True
except Exception as e:
    print(f"[WARN] ML engine not loaded: {e}")
    ML_ENABLED = False

# Weather-informed charging scheduler (safe: never blocks the app)
try:
    from weather import get_weather_decision
    WEATHER_ENABLED = True
except Exception as e:
    print(f"[WARN] Weather module not loaded: {e}")
    WEATHER_ENABLED = False

# Dashboard -> ESP32 command pipeline (Option A: ESP32 polls via /api/data response)
try:
    from commands import set_command, pop_command, peek_command
    COMMANDS_ENABLED = True
except Exception as e:
    print(f"[WARN] Command module not loaded: {e}")
    COMMANDS_ENABLED = False

app = Flask(__name__)

# ---- anomaly notification debounce ----
# ML flags ~2% of readings as anomalies (every 2s that is a lot). We only log an
# event after several consecutive anomalies, then stay quiet for a cooldown, so
# the activity log and bell are not flooded.
_anom = {"streak": 0, "last_logged": 0.0}
ANOM_CONFIRM = 5          # need this many consecutive anomalies
ANOM_COOLDOWN = 600       # then stay quiet for 10 minutes
_soc_low_logged = 0.0     # last time we logged an SOC-low warning
_temp_hi_logged = 0.0     # last time we logged an over-temp warning
COND_COOLDOWN = 600

def _maybe_log_from_ml(data, ml):
    """Turn ML output + live data into debounced events (anomaly / SOC low /
    over-temp). Never raises."""
    import time as _t
    now = _t.time()
    try:
        # --- anomaly (needs confirmation + cooldown) ---
        if ml and ml.get("anomaly") and ml.get("ml_warm"):
            _anom["streak"] += 1
            if _anom["streak"] >= ANOM_CONFIRM and (now - _anom["last_logged"]) > ANOM_COOLDOWN:
                # try to name a likely cause from the live row
                cause = "unusual readings"
                try:
                    if float(data.get("battery_temperature", 0)) >= 45: cause = "high temperature"
                    elif 0 <= float(data.get("soc", 100)) < 20:          cause = "low state of charge"
                except Exception:
                    pass
                log_event("critical", "anomaly", f"Anomaly detected: {cause}.")
                _anom["last_logged"] = now
                _anom["streak"] = 0
        else:
            _anom["streak"] = 0

        # --- SOC critically low ---
        global _soc_low_logged, _temp_hi_logged
        try:
            soc = float(data.get("soc", -1))
            if 0 <= soc < 20 and (now - _soc_low_logged) > COND_COOLDOWN:
                log_event("warning", "soc_low", f"Battery SOC low: {soc:.0f}%.")
                _soc_low_logged = now
        except Exception:
            pass

        # --- over-temperature ---
        try:
            temp = float(data.get("battery_temperature", 0))
            if temp >= 45 and (now - _temp_hi_logged) > COND_COOLDOWN:
                log_event("warning", "temp_high", f"Battery temperature high: {temp:.1f} C.")
                _temp_hi_logged = now
        except Exception:
            pass
    except Exception as e:
        print(f"[EVENT DERIVE ERROR] {e}")

# =====================================================
# Database Initialization
# =====================================================
create_database()
create_events_table()

# =====================================================
# Dashboard
# =====================================================
# A safe default so the dashboard renders even when the database is empty
# (e.g. right after a reset, before the ESP32 has sent its first packet).
EMPTY_LATEST = {
    "solar_voltage": 0, "solar_current": 0, "solar_power": 0,
    "battery_voltage": 0, "battery_current": 0, "battery_power": 0,
    "battery_temperature": 0, "soc": 0,
    "charge_voltage": 0, "charge_current": 0, "charge_power": 0,
    "ac_current": 0, "load_current": 0, "load_power": 0, "load_level": 0,
    "mosfet1_state": 0, "mosfet2_state": 0, "mosfet3_state": 0,
    "relay_state": 0, "ac_relay_state": 0,
    "charging_source": "None", "system_state": "Waiting",
    "energy_harvested": 0, "uptime_s": 0, "uptime": "0s",
    "wifi_rssi": 0, "free_heap": 0, "timestamp": "—",
}


@app.route("/")
def home():
    try:
        latest = get_latest_data()
    except Exception as e:
        print(f"\n[ERROR] home: {e}")
        latest = None
    # Never hand the template a None: fall back to a zero-filled row so an
    # empty database (fresh reset) still renders instead of raising.
    if latest is None:
        latest = EMPTY_LATEST
    else:
        latest = dict(latest)
    return render_template("dashboard.html", latest=latest)

# =====================================================
# API
# =====================================================

@app.route("/api/latest", methods=["GET"])
def api_latest():

    try:
        latest = get_latest_data()
    except Exception as e:
        print(f"\n[ERROR] api_latest: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    if not latest:
        return jsonify({
            "error": "No data available"
        }), 404

    return jsonify(dict(latest))


@app.route("/api/history", methods=["GET"])
def api_history():

    # Default to the last 6 hours, downsampled, for the trend charts.
    # ?hours=N overrides the window if needed.
    try:
        hours = request.args.get("hours", default=6, type=int)
        hours = max(1, min(hours, 48))          # clamp to a sane range
        rows = get_history_window(hours=hours, max_points=360)
    except Exception as e:
        print(f"\n[ERROR] api_history: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    history = [dict(row) for row in rows]

    return jsonify(history)


@app.route("/api/data", methods=["POST"])
def api_data():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "status": "error",
            "message": "Invalid JSON"
        }), 400

    # Guard against a packet that is missing a field. Without this a
    # missing key raises KeyError inside validate_data and becomes a 500.
    try:
        errors = validate_data(data)
    except KeyError as e:
        return jsonify({
            "status": "error",
            "message": f"Missing field: {e}"
        }), 400

    if errors:
        return jsonify({
            "status": "error",
            "errors": errors
        }), 400

    try:

        insert_data(data)

        # ---- ML prediction (non-blocking: failure never stops data storage) ----
        ml_result = None
        if ML_ENABLED:
            try:
                ml_result = ml_predict(data)
                app.config["LAST_ML"] = ml_result
                _maybe_log_from_ml(data, ml_result)
            except Exception as ml_err:
                print(f"[ML ERROR] {ml_err}")

        print("\n" + "=" * 70)
        print("               NEW SENSOR DATA RECEIVED")
        print("=" * 70)

        print(f"Time                 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        print("\n[SOLAR]")
        print(f"Voltage              : {data['solar_voltage']} V")
        print(f"Current              : {data['solar_current']} A")
        print(f"Power                : {data['solar_power']} W")

        print("\n[BATTERY]")
        print(f"Voltage              : {data['battery_voltage']} V")
        print(f"Current              : {data['battery_current']} A")
        print(f"Power                : {data['battery_power']} W")
        print(f"Temperature          : {data['battery_temperature']} °C")
        print(f"SOC                  : {data['soc']} %")

        print("\n[CHARGER]")
        print(f"Charge Voltage       : {data['charge_voltage']} V")
        print(f"Charge Current       : {data['charge_current']} A")
        print(f"Charge Power         : {data['charge_power']} W")

        print("\n[AC]")
        print(f"AC Current           : {data['ac_current']} A")

        print("\n[LOAD]")
        print(f"Load Current         : {data['load_current']} A")
        print(f"Load Power           : {data['load_power']} W")
        print(f"Load Level           : {data['load_level']}")

        print("\n[STATE]")
        print(f"Charging Source      : {data['charging_source']}")
        print(f"System State         : {data['system_state']}")

        print("\n[SWITCHES]")
        print(f"Relay                : {data['relay_state']}")
        print(f"AC Relay             : {data['ac_relay_state']}")
        print(f"MOSFET1              : {data['mosfet1_state']}")
        print(f"MOSFET2              : {data['mosfet2_state']}")
        print(f"MOSFET3              : {data['mosfet3_state']}")

        print("\n[SYSTEM]")
        print(f"Energy Harvested     : {data['energy_harvested']} Wh")
        print(f"Uptime               : {data['uptime_s']} s")
        print(f"WiFi RSSI            : {data['wifi_rssi']} dBm")
        print(f"Free Heap            : {data['free_heap']} Bytes")

        if ml_result:
            print("\n[ML PREDICTION]")
            print(f"Anomaly              : {ml_result['anomaly']}  (score {ml_result['anomaly_score']})")
            print(f"Operating Mode       : {ml_result['cluster_name']}")
            print(f"Predicted Load Level : {ml_result['predicted_load_level']}")
            print(f"SOC Trend            : {ml_result['soc_trend']}")
            print(f"ML Warm              : {ml_result['ml_warm']}")

        print("=" * 70)
        print("DATA STORED SUCCESSFULLY")
        print("=" * 70 + "\n")

        # ---- pending dashboard command for the ESP32 (Option A) ----
        # ESP32 reads this from the POST response and applies it once.
        # Its own safety layer may still override/ignore it.
        command = None
        if COMMANDS_ENABLED:
            try:
                command = pop_command()
                if command:
                    print(f"\n[COMMAND -> ESP32] {command}")
            except Exception as cmd_err:
                print(f"[COMMAND ERROR] {cmd_err}")

        return jsonify({
            "status": "success",
            "message": "Data Stored Successfully",
            "ml": ml_result,
            "command": command
        }), 200

    except Exception as e:

        print(f"\n[ERROR] {e}")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/api/ml", methods=["GET"])
def api_ml():
    # Latest ML prediction for the dashboard to poll.
    # Returns the last computed result, or a safe default before the first reading.
    default = {
        "anomaly": False,
        "anomaly_score": 0.0,
        "cluster_id": None,
        "cluster_name": "—",
        "predicted_load_level": None,
        "soc_trend": "—",
        "ml_warm": False,
        "ml_enabled": ML_ENABLED,
    }
    last = app.config.get("LAST_ML")
    if not last:
        return jsonify(default)

    result = dict(last)
    result["ml_enabled"] = ML_ENABLED
    return jsonify(result)


@app.route("/api/weather", methods=["GET"])
def api_weather():
    # Weather-informed charging hint for the dashboard.
    if not WEATHER_ENABLED:
        return jsonify({"status": "disabled", "recommend_precharge": False})
    try:
        return jsonify(get_weather_decision())
    except Exception as e:
        print(f"[WEATHER ERROR] {e}")
        return jsonify({
            "status": "error",
            "recommend_precharge": False,
            "message": str(e)
        })


@app.route("/api/command", methods=["GET", "POST"])
def api_command():
    # GET  -> show what command is currently queued for the ESP32
    # POST -> queue a new command from the dashboard (whitelisted keys only)
    if not COMMANDS_ENABLED:
        return jsonify({"status": "disabled"})

    if request.method == "GET":
        return jsonify({"status": "ok", "pending": peek_command()})

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    accepted, rejected = set_command(payload)
    # log accepted commands to the activity feed
    for k, v in accepted.items():
        nice = {"mosfet1": "Fan", "mosfet2": "Bulb 1", "mosfet3": "Bulb 2",
                "grid_relay": "Grid relay", "charge_mode": "Charge mode"}.get(k, k)
        log_event("info", "command", f"{nice} -> {v}")
    return jsonify({
        "status": "ok",
        "accepted": accepted,
        "rejected": rejected,
        "pending": peek_command()
    })


@app.route("/api/events", methods=["GET"])
def api_events():
    # Activity log + unseen count for the notification bell.
    try:
        rows = get_events(limit=50)
        events = [dict(r) for r in rows]
        return jsonify({"status": "ok", "events": events, "unseen": get_unseen_count()})
    except Exception as e:
        print(f"[EVENTS ERROR] {e}")
        return jsonify({"status": "error", "events": [], "unseen": 0})


@app.route("/api/events/seen", methods=["POST"])
def api_events_seen():
    # Called when the user opens the bell; clears the unseen badge.
    try:
        mark_events_seen()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/status", methods=["GET"])
def api_status():

    try:
        latest = get_latest_data()
        records = get_total_records()
    except Exception as e:
        print(f"\n[ERROR] api_status: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    return jsonify({

        "database": "connected",
        "records": records,
        "latest_timestamp": latest["timestamp"] if latest else None

    })


# =====================================================
# CSV Export
# =====================================================

@app.route("/download/csv", methods=["GET"])
def download_csv():

    filename = "data/csv/solar_data.csv"

    try:
        export_csv(filename)
    except Exception as e:
        print(f"\n[ERROR] download_csv: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    return send_file(
        filename,
        as_attachment=True,
        download_name="solar_data.csv"
    )


# =====================================================
# Health Check
# =====================================================

@app.route("/health", methods=["GET"])
def health():

    try:
        records = get_total_records()
    except Exception as e:
        print(f"\n[ERROR] health: {e}")
        return jsonify({
            "status": "degraded",
            "database": "error",
            "message": str(e)
        }), 500

    return jsonify({

        "status": "online",
        "database": "connected",
        "records": records,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    })


# =====================================================
# Main
# =====================================================

if __name__ == "__main__":

    print("\n" + "=" * 45)
    print("         SOLAR AI BACKEND STARTED")
    print("=" * 45)
    print(f"Dashboard : http://capstonepi.local:{PORT}")
    print(f"API       : http://capstonepi.local:{PORT}/api/data")
    print(f"ML        : {'enabled' if ML_ENABLED else 'DISABLED'}")
    print(f"Weather   : {'enabled' if WEATHER_ENABLED else 'DISABLED'}")
    print(f"Commands  : {'enabled' if COMMANDS_ENABLED else 'DISABLED'}")
    print("Waiting for ESP32...\n")

    app.run(
        host=HOST,
        port=PORT,
        debug=DEBUG
    )
