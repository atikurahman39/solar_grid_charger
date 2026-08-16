# Solar AI Charger — ESP32 Firmware

Modular Arduino firmware for the Intelligent Hybrid Solar-Grid Charger.

## Files

```
Solar_AI_ESP32/
├── Solar_AI_ESP32.ino   ← Main (setup + loop)
├── config.h             ← All pins + settings (EDIT THIS)
├── sensor.h / .cpp      ← INA219 x2 + DS18B20 reading, SOC
├── control.h / .cpp     ← Rule-based safety AI, relay, MOSFET, LEDs
├── display.h / .cpp     ← OLED SSD1309 SPI (U8g2)
├── wifi_sender.h / .cpp ← Sends JSON to Raspberry Pi
├── sd_logger.h / .cpp   ← Optional SD backup
└── README.md
```

## Before Uploading

### 1. Install Libraries (Arduino IDE → Library Manager)

- Adafruit INA219
- OneWire
- DallasTemperature
- U8g2 (by oliver)

### 2. Edit config.h

Change these lines:

```cpp
#define WIFI_SSID      "YOUR_WIFI_NAME"
#define WIFI_PASS      "YOUR_WIFI_PASSWORD"
#define PI_SERVER_URL  "http://capstonepi.local:5000/api/data"
```

If capstonepi.local does not work, use the Pi IP address:
```cpp
#define PI_SERVER_URL  "http://192.168.1.xxx:5000/api/data"
```

### 3. Board Settings

- Board: ESP32 Dev Module
- Upload Speed: 921600
- Select correct COM port

## How to Open in Arduino IDE

1. Put all files in a folder named `Solar_AI_ESP32`
2. Double-click `Solar_AI_ESP32.ino`
3. Arduino IDE opens all tabs automatically
4. Click Upload

## Data Flow

```
Every 2 seconds:
  Read sensors (INA219 x2, DS18B20)
    ↓
  Apply safety rules (temp, voltage, SOC)
    ↓
  Update OLED display
    ↓
  Send JSON to Raspberry Pi (WiFi)
    ↓
  Log to SD card (if enabled)
```

## JSON Sent to Pi

Matches server.py /api/data exactly:

```json
{
  "pv_v": 18.2, "pv_i": 3.800,
  "bat_v": 13.40, "bat_i": 2.100,
  "temp": 31.2, "soc": 68.0,
  "load_i": 1.500, "mode": "CC",
  "relay": 1, "mosfet": 1
}
```

## Rule-Based Safety AI

| Condition | Action |
|-----------|--------|
| Temp > 50°C | Cut charging + load |
| Voltage > 14.6V | Cut charging |
| SOC < 20% | Cut load |
| Temp > 45°C | Warning beep |
| Normal | Charging + load ON |

## Features Toggle (config.h)

```cpp
#define ENABLE_WIFI    true   // Send to Pi
#define ENABLE_SD      false  // SD backup (set true when module connected)
#define ENABLE_OLED    true   // OLED display
```

## Push Button

Press to reset SOC to 100% (use when battery is known fully charged).

## Notes on SOC

SOC uses Coulomb counting. It starts at 50% estimate. For accurate SOC:
1. Fully charge battery
2. Press button to set SOC = 100%
3. From there it tracks accurately via current integration
