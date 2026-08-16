import sqlite3
from datetime import datetime

DATABASE = "data/solar.db"


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solar_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT NOT NULL,

            solar_voltage REAL,
            solar_current REAL,
            solar_power REAL,

            battery_voltage REAL,
            battery_current REAL,
            battery_power REAL,

            battery_temperature REAL,

            load_current REAL,
            load_power REAL,

            soc REAL,

            relay_state INTEGER,
            mosfet_state INTEGER,

            charging_mode TEXT
        )
    """)

    conn.commit()
    conn.close()

def insert_data(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO solar_data (
            timestamp,
            solar_voltage,
            solar_current,
            solar_power,
            battery_voltage,
            battery_current,
            battery_power,
            battery_temperature,
            load_current,
            load_power,
            soc,
            relay_state,
            mosfet_state,
            charging_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data["solar_voltage"],
        data["solar_current"],
        data["solar_power"],
        data["battery_voltage"],
        data["battery_current"],
        data["battery_power"],
        data["battery_temperature"],
        data["load_current"],
        data["load_power"],
        data["soc"],
        data["relay_state"],
        data["mosfet_state"],
        data["charging_mode"]
    ))

    conn.commit()
    conn.close()
def get_latest_data():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM solar_data
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

    return row
