VALID_SYSTEM_STATES = [
    "Charging",
    "Discharging"
]

VALID_CHARGING_SOURCES = [
    "Solar",
    "Grid",
    "Both",
    "None"
]


def validate_data(data):

    errors = []

    # Solar
    if not (0 <= data["solar_voltage"] <= 30):
        errors.append("Invalid Solar Voltage")

    if not (0 <= data["solar_current"] <= 20):
        errors.append("Invalid Solar Current")

    if not (0 <= data["solar_power"] <= 1000):
        errors.append("Invalid Solar Power")

    # Battery
    if not (0 <= data["battery_voltage"] <= 20):
        errors.append("Invalid Battery Voltage")

    if not (-20 <= data["battery_current"] <= 20):
        errors.append("Invalid Battery Current")

    if not (-500 <= data["battery_power"] <= 1000):
        errors.append("Invalid Battery Power")

    if not (-20 <= data["battery_temperature"] <= 100):
        errors.append("Invalid Battery Temperature")

    # SOC
    # -1 is a valid reading: the firmware sends it when no battery is connected
    # (SOC cannot be measured). Any other negative or >100 value is invalid.
    if data["soc"] != -1 and not (0 <= data["soc"] <= 100):
        errors.append("Invalid SOC")

    # Charger
    if not (0 <= data["charge_voltage"] <= 30):
        errors.append("Invalid Charge Voltage")

    if not (0 <= data["charge_current"] <= 20):
        errors.append("Invalid Charge Current")

    if not (0 <= data["charge_power"] <= 1000):
        errors.append("Invalid Charge Power")

    # AC
    if not (0 <= data["ac_current"] <= 20):
        errors.append("Invalid AC Current")

    # Load
    if not (0 <= data["load_current"] <= 20):
        errors.append("Invalid Load Current")

    if not (0 <= data["load_power"] <= 1000):
        errors.append("Invalid Load Power")

    if not (0 <= data["load_level"] <= 7):
        errors.append("Invalid Load Level")

    # Relay
    if data["relay_state"] not in [0, 1]:
        errors.append("Invalid Relay State")

    if data["ac_relay_state"] not in [0, 1]:
        errors.append("Invalid AC Relay State")

    # MOSFET
    if data["mosfet1_state"] not in [0, 1]:
        errors.append("Invalid MOSFET1 State")

    if data["mosfet2_state"] not in [0, 1]:
        errors.append("Invalid MOSFET2 State")

    if data["mosfet3_state"] not in [0, 1]:
        errors.append("Invalid MOSFET3 State")

    # Charging Source
    if data["charging_source"] not in VALID_CHARGING_SOURCES:
        errors.append("Invalid Charging Source")

    # System State
    if data["system_state"] not in VALID_SYSTEM_STATES:
        errors.append("Invalid System State")

    # Energy Harvested
    if data["energy_harvested"] < 0:
        errors.append("Invalid Energy Harvested")

    # Uptime
    if data["uptime_s"] < 0:
        errors.append("Invalid Uptime")

    # WiFi RSSI
    if not (-120 <= data["wifi_rssi"] <= 0):
        errors.append("Invalid WiFi RSSI")

    # Free Heap
    if data["free_heap"] < 0:
        errors.append("Invalid Free Heap")

    return errors
