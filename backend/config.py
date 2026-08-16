"""
Project Configuration
Capstone Solar AI
"""

from pathlib import Path

# -------------------------
# Project Paths
# -------------------------

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
CSV_DIR = DATA_DIR / "csv"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backup"

DATABASE = DATA_DIR / "solar.db"

# -------------------------
# UART
# -------------------------

SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1

# -------------------------
# Flask
# -------------------------

HOST = "0.0.0.0"
PORT = 5000
DEBUG = False

# -------------------------
# Data Collection
# -------------------------

PACKET_INTERVAL = 1

# -------------------------
# Logging
# -------------------------

APP_LOG = LOG_DIR / "app.log"
SERIAL_LOG = LOG_DIR / "serial.log"
ERROR_LOG = LOG_DIR / "error.log"

# -------------------------
# Create Required Folders
# -------------------------

DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
