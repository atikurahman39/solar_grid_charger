"""
commands.py  -  holds pending commands from the dashboard for the ESP32.

Flow (Option A: ESP32 polls via its existing POST):
    1. Dashboard button  -> POST /api/command  -> set_command(...)
    2. ESP32 POSTs sensor data to /api/data as usual
    3. The /api/data response now carries any pending command
    4. ESP32 applies it (relay / mosfet / mode), then it is cleared

The ESP32 firmware's own safety layer (over-temp / over-voltage) always has
the final say and may ignore or override a command.

Only whitelisted keys/values are accepted, so a bad dashboard request can
never push an arbitrary payload to the hardware.
"""

import threading

# --- what the dashboard is allowed to command ---
# key -> set of allowed values
ALLOWED = {
    "grid_relay": {"ON", "OFF"},
    "mosfet1":    {"ON", "OFF"},     # Fan
    "mosfet2":    {"ON", "OFF"},     # Bulb 1
    "mosfet3":    {"ON", "OFF"},     # Bulb 2
    "charge_mode": {"auto", "solar", "grid", "hybrid"},
}

_lock = threading.Lock()
_pending = {}          # accumulated command, sent on next ESP32 poll


def set_command(new):
    """Merge a validated command from the dashboard into the pending set.
    Returns (accepted_dict, rejected_list)."""
    accepted, rejected = {}, []
    if not isinstance(new, dict):
        return accepted, ["payload must be an object"]

    for key, val in new.items():
        if key in ALLOWED and val in ALLOWED[key]:
            accepted[key] = val
        else:
            rejected.append(f"{key}={val}")

    if accepted:
        with _lock:
            _pending.update(accepted)
    return accepted, rejected


def pop_command():
    """Return the pending command and clear it. Called from /api/data so the
    ESP32 receives it exactly once."""
    with _lock:
        if not _pending:
            return None
        cmd = dict(_pending)
        _pending.clear()
        return cmd


def peek_command():
    """Return the pending command without clearing (for the dashboard to show
    what is queued)."""
    with _lock:
        return dict(_pending) if _pending else None
