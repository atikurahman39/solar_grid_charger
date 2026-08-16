from database import create_database, insert_data, get_latest_data

create_database()

sample_data = {
    "solar_voltage": 20.5,
    "solar_current": 3.2,
    "solar_power": 65.6,
    "battery_voltage": 12.8,
    "battery_current": 2.7,
    "battery_power": 34.6,
    "battery_temperature": 31.4,
    "load_current": 1.2,
    "load_power": 15.4,
    "soc": 72,
    "relay_state": 1,
    "mosfet_state": 1,
    "charging_mode": "CC"
}

insert_data(sample_data)

latest = get_latest_data()

print("Latest Reading")
print("----------------")
print(f"Time: {latest['timestamp']}")
print(f"Solar Voltage: {latest['solar_voltage']} V")
print(f"Solar Current: {latest['solar_current']} A")
print(f"Battery Voltage: {latest['battery_voltage']} V")
print(f"Battery Temperature: {latest['battery_temperature']} °C")
print(f"SOC: {latest['soc']} %")
