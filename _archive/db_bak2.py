import sqlite3
from datetime import datetime
import csv

from config import DATABASE


def get_connection():
    # timeout=10 gives SQLite a 10s busy timeout: instead of failing
    # instantly on a lock, it waits and retries for up to 10 seconds.
    conn = sqlite3.connect(
        DATABASE,
        timeout=10,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row

    # WAL lets one writer and many readers work at the same time,
    # so the dashboard read and the ESP32 write stop blocking each other.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    return conn


def create_database():

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS solar_data(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            solar_voltage REAL,
            solar_current REAL,
            solar_power REAL,

            battery_voltage REAL,
            battery_current REAL,
            battery_power REAL,

            battery_temperature REAL,

            soc REAL,

            charge_voltage REAL,
            charge_current REAL,
            charge_power REAL,

            ac_current REAL,

            load_current REAL,
            load_power REAL,
            load_level INTEGER,

            mosfet1_state INTEGER,
            mosfet2_state INTEGER,
            mosfet3_state INTEGER,

            relay_state INTEGER,
            ac_relay_state INTEGER,

            charging_source TEXT,
            system_state TEXT,

            energy_harvested REAL,

            uptime_s INTEGER,
            wifi_rssi INTEGER,
            free_heap INTEGER

        )
        """)

        conn.commit()
    finally:
        conn.close()


def insert_data(data):

    conn = get_connection()
    try:
        # "with conn:" wraps the insert in a transaction that commits on
        # success and rolls back on error, so a failed write never leaves
        # a lock hanging around.
        with conn:
            conn.execute("""
            INSERT INTO solar_data(

                id,
                timestamp,

                solar_voltage,
                solar_current,
                solar_power,

                battery_voltage,
                battery_current,
                battery_power,

                battery_temperature,

                soc,

                charge_voltage,
                charge_current,
                charge_power,

                ac_current,

                load_current,
                load_power,
                load_level,

                mosfet1_state,
                mosfet2_state,
                mosfet3_state,

                relay_state,
                ac_relay_state,

                charging_source,
                system_state,

                energy_harvested,

                uptime_s,
                wifi_rssi,
                free_heap

            )

            VALUES(
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?
            )

            """, (

                None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

                data["solar_voltage"],
                data["solar_current"],
                data["solar_power"],

                data["battery_voltage"],
                data["battery_current"],
                data["battery_power"],

                data["battery_temperature"],

                data["soc"],

                data["charge_voltage"],
                data["charge_current"],
                data["charge_power"],

                data["ac_current"],

                data["load_current"],
                data["load_power"],
                data["load_level"],

                data["mosfet1_state"],
                data["mosfet2_state"],
                data["mosfet3_state"],

                data["relay_state"],
                data["ac_relay_state"],

                data["charging_source"],
                data["system_state"],

                data["energy_harvested"],

                data["uptime_s"],
                data["wifi_rssi"],
                data["free_heap"]

            ))
    finally:
        conn.close()


def get_latest_data():

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM solar_data
            ORDER BY id DESC
            LIMIT 1
        """)

        return cursor.fetchone()
    finally:
        conn.close()


def get_history(limit=100):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM solar_data
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))

        return cursor.fetchall()
    finally:
        conn.close()


def get_history_window(hours=6, max_points=360):
    """Return chart history for roughly the last `hours` hours, thinned down to
    at most `max_points` rows so the charts stay light on the Pi and in the
    browser.

    The raw log is one row every ~2 s, so 6 hours is ~10,800 rows. Sending all
    of them would be heavy, so we keep only every Nth row (a simple stride
    downsample) while preserving the real timestamps and values.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # How many rows fall inside the time window. Uses SQLite datetime math
        # on the stored TEXT timestamp ("YYYY-MM-DD HH:MM:SS").
        cursor.execute(
            """
            SELECT COUNT(*) AS n
            FROM solar_data
            WHERE timestamp >= datetime('now', 'localtime', ?)
            """,
            (f'-{int(hours)} hours',),
        )
        row = cursor.fetchone()
        n = row["n"] if row and row["n"] else 0

        if n == 0:
            # No rows in the window (e.g. right after a reset): fall back to the
            # most recent rows so the charts still show something.
            cursor.execute(
                "SELECT * FROM solar_data ORDER BY id DESC LIMIT ?",
                (max_points,),
            )
            rows = cursor.fetchall()
            return list(reversed(rows))

        # Stride so that n rows collapse to <= max_points.
        stride = max(1, n // max_points)

        # Pull the windowed rows oldest-first, keeping every `stride`-th one.
        # ROW_NUMBER lets us pick evenly spaced samples in pure SQL.
        cursor.execute(
            """
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (ORDER BY id ASC) AS rn
                FROM solar_data
                WHERE timestamp >= datetime('now', 'localtime', ?)
            )
            WHERE rn % ? = 0
            ORDER BY id ASC
            """,
            (f'-{int(hours)} hours', stride),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def get_total_records():

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM solar_data")

        return cursor.fetchone()[0]
    finally:
        conn.close()


def export_csv(filename):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM solar_data
            ORDER BY id ASC
        """)

        rows = cursor.fetchall()
    finally:
        conn.close()

    with open(filename, "w", newline="") as csvfile:

        writer = csv.writer(csvfile)

        writer.writerow([
            "id",
            "timestamp",

            "solar_voltage",
            "solar_current",
            "solar_power",

            "battery_voltage",
            "battery_current",
            "battery_power",

            "battery_temperature",

            "soc",

            "charge_voltage",
            "charge_current",
            "charge_power",

            "ac_current",

            "load_current",
            "load_power",
            "load_level",

            "mosfet1_state",
            "mosfet2_state",
            "mosfet3_state",

            "relay_state",
            "ac_relay_state",

            "charging_source",
            "system_state",

            "energy_harvested",

            "uptime_s",
            "wifi_rssi",
            "free_heap"
        ])

        for row in rows:
            writer.writerow(list(row))

    return filename
