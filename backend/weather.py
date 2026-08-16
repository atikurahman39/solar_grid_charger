"""
weather.py  -  weather-informed smart charging scheduler.

Fetches a short cloud / solar-radiation forecast for the site (Kuratoli, Kuril,
Dhaka) from the free Open-Meteo API and turns it into a simple charging hint:

    if low solar is expected in the coming daytime hours,
    pre-charge from the grid now (while power is cheap / available).

Design notes
------------
* No API key is required (Open-Meteo free tier).
* The forecast is cached: the network is only hit once every REFRESH_MIN
  minutes, never on every 2-second sensor packet.
* Every network call is wrapped in try/except. If the internet is down the
  module returns the last good forecast, or a safe "unknown" result. It must
  never crash the Flask app.
"""

import time
import threading
from datetime import datetime

import requests

# ---- site location (Kuratoli, Kuril, Dhaka) ----
LATITUDE  = 23.8225
LONGITUDE = 90.4247
TIMEZONE  = "Asia/Dhaka"

# ---- behaviour ----
REFRESH_MIN      = 30          # how often to hit the network (minutes)
LOW_SOLAR_CLOUD  = 60          # mean daytime cloud cover % above this = "low solar"
DAY_START_HOUR   = 8           # daytime window used for the decision
DAY_END_HOUR     = 17
REQUEST_TIMEOUT  = 8           # seconds

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# ---- cache (thread-safe) ----
_lock = threading.Lock()
_cache = {
    "ts": 0.0,          # epoch seconds of last successful fetch
    "data": None,       # last good result dict
}


def _fetch_forecast():
    """Hit Open-Meteo once. Returns the parsed hourly forecast or raises."""
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "cloud_cover,shortwave_radiation",
        "forecast_days": 2,
        "timezone": TIMEZONE,
    }
    r = requests.get(_OPEN_METEO, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _decide(forecast):
    """Turn a raw Open-Meteo response into a charging decision dict."""
    hourly = forecast.get("hourly", {})
    times  = hourly.get("time", [])
    clouds = hourly.get("cloud_cover", [])
    rad    = hourly.get("shortwave_radiation", [])

    # look at the NEXT daytime window (tomorrow's generating hours)
    day_clouds = []
    day_rad = []
    for t, c, s in zip(times, clouds, rad):
        try:
            hr = datetime.strptime(t, "%Y-%m-%dT%H:%M").hour
        except Exception:
            continue
        if DAY_START_HOUR <= hr <= DAY_END_HOUR:
            if c is not None:
                day_clouds.append(c)
            if s is not None:
                day_rad.append(s)

    if not day_clouds:
        return {
            "status": "unknown",
            "recommend_precharge": False,
            "reason": "no daytime forecast available",
        }

    mean_cloud = sum(day_clouds) / len(day_clouds)
    peak_rad   = max(day_rad) if day_rad else 0.0
    low_solar  = mean_cloud > LOW_SOLAR_CLOUD

    return {
        "status": "ok",
        "mean_cloud_pct": round(mean_cloud, 1),
        "peak_radiation_wm2": round(peak_rad, 1),
        "low_solar_expected": low_solar,
        "recommend_precharge": low_solar,
        "reason": (
            "Low solar expected tomorrow (cloudy). Pre-charge from grid tonight."
            if low_solar else
            "Good solar expected tomorrow. Rely on solar; no grid pre-charge needed."
        ),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_weather_decision(force=False):
    """Public entry point. Returns the cached decision, refreshing from the
    network only if the cache is older than REFRESH_MIN (or force=True)."""
    now = time.time()
    with _lock:
        fresh = _cache["data"] is not None and \
            (now - _cache["ts"]) < REFRESH_MIN * 60
        if fresh and not force:
            return _cache["data"]

    # cache stale -> try to refresh (outside the lock so we don't block others)
    try:
        forecast = _fetch_forecast()
        decision = _decide(forecast)
        with _lock:
            _cache["ts"] = now
            _cache["data"] = decision
        return decision
    except Exception as e:
        # network failed: return last good data if we have it, else a safe stub
        with _lock:
            if _cache["data"] is not None:
                stale = dict(_cache["data"])
                stale["status"] = "stale"
                stale["error"] = str(e)
                return stale
        return {
            "status": "offline",
            "recommend_precharge": False,
            "reason": "weather service unreachable",
            "error": str(e),
        }


if __name__ == "__main__":
    # ---- offline self-test with a fake forecast (no network) ----
    import weather as W

    def fake_cloudy():
        hrs = [f"2026-08-02T{h:02d}:00" for h in range(24)] + \
              [f"2026-08-03T{h:02d}:00" for h in range(24)]
        return {"hourly": {
            "time": hrs,
            "cloud_cover": [80] * len(hrs),
            "shortwave_radiation": [120] * len(hrs),
        }}

    def fake_sunny():
        hrs = [f"2026-08-02T{h:02d}:00" for h in range(24)]
        return {"hourly": {
            "time": hrs,
            "cloud_cover": [15] * len(hrs),
            "shortwave_radiation": [850] * len(hrs),
        }}

    print("CLOUDY case:", W._decide(fake_cloudy()))
    print("SUNNY  case:", W._decide(fake_sunny()))
