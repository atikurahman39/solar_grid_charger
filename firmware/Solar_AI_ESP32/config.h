#ifndef CONFIG_H
#define CONFIG_H

// =====================================================
//  Intelligent Hybrid Solar-Grid Charger
//  ESP32 Firmware Configuration
//  All pins, addresses, and settings in one place
// =====================================================

#define PROJECT_NAME   "Solar AI Charger v1.0"
#define SERIAL_BAUD    115200

// ---------- I2C BUS (INA238 x2 + INA237) ----------
#define I2C_SDA        21
#define I2C_SCL        22
#define SOLAR_INA_ADDR    0x41   // INA238 (PV side) - A0 soldered to VDD
#define BATTERY_INA_ADDR  0x40   // INA238 (Battery discharge line) - default
#define CHARGE_INA_ADDR   0x44   // INA237 (Charge line C+) - hybrid charge current

// ---------- TEMPERATURE ----------
#define TEMP_PIN       4         // DS18B20 (needs 4.7k pull-up)

// ---------- OLED SSD1309 (SPI) ----------
#define OLED_SCK       18
#define OLED_MOSI      23
#define OLED_CS        5
#define OLED_DC        16
#define OLED_RST       17

// ---------- STATUS LEDs ----------
#define LED_GREEN      27
#define LED_RED        13
#define LED_BLUE       12

// ---------- BUZZER + BUTTON ----------
#define BUZZER_PIN     32
#define BUTTON_PIN     33        // Push button (SOC reset) - INPUT_PULLUP

// ---------- CONTROL OUTPUTS ----------
#define RELAY_PIN      26        // Charging control (main/MPPT path)
#define MOSFET1_PIN    25        // Load control #1 (Fan)
#define MOSFET2_PIN    15        // Load control #2 (Bulb1)
#define MOSFET3_PIN    2         // Load control #3 (Bulb2) - moved from 19, SD removed
#define AC_RELAY_PIN   14        // AC charger relay (was Yellow LED)

// ---------- VOLTAGE DIVIDER ----------
#define VDIV_PIN       34        // ADC backup battery voltage

// ---------- BATTERY SETTINGS ----------
#define BATTERY_CAPACITY_AH   30.0    // 30Ah LiFePO4
#define BATTERY_V_FULL        14.4
#define BATTERY_V_FLOAT       13.6
#define BATTERY_V_MIN         11.0
#define TEMP_MAX              50.0    // Emergency cutoff (latches ON here)
#define TEMP_RECOVERY         35.0    // Must cool to here before the over-temp latch clears
#define TEMP_WARN             45.0    // Warning threshold
#define SOC_LOW_CUTOFF        20.0    // Below this: all loads OFF
#define SOC_RECOVERY          30.0    // Must reach this before loads resume after cutoff
#define SOC_REDUCED_LOAD      30.0    // Below this: only ONE load (the fan) may run
#define SOC_MID_ZONE          60.0    // While charging, below this at most TWO loads
#define SOC_CUTOFF_CLEAR      22.0    // Loads may return once SOC climbs back to here
#define CHARGE_DETECT_A        0.2    // charge current above this = battery is charging

// ---- SOC estimation tuning ----
#define SOC_REST_LOAD_A        0.5    // below this load, the battery is "at rest":
                                      // its voltage is trustworthy for correction
#define SOC_VCORRECT_REST      0.02   // voltage-correction weight when at rest (2%)
#define SOC_VCORRECT_LOADED    0.0    // voltage-correction weight under load (off):
                                      // loaded voltage sags, so ignore it
#define SOC_VOLT_SMOOTH        0.10   // low-pass factor for the voltage used in SOC
                                      // (0.10 = slow, ignores brief load dips)
#define SOC_FULL_VOLT          14.3   // at/above this while charging -> pack is full
#define SOC_FULL_RESET_A       1.0    // ...and charge current has tapered below this
                                      // -> snap SOC to 100% (absorption complete)
#define CHARGE_STATE_CONFIRM_MS 30000  // charging/discharging must hold 30 s to count
#define FORCED_CHANGE_GAP_MS   120000  // min 2 min between limit-driven load changes
#define CV_ENTRY_V            14.2    // absorption voltage: CC ends, CV begins
#define FLOAT_TAPER_A          1.5    // C/20 for 30Ah: below this in CV = Float stage

// ---------- HYBRID CHARGING (Solar priority, AC backup) ----------
// AC charger runs only while the PV side is idle. Two solar thresholds give
// hysteresis so the relay does not chatter when clouds pass.
// PV is considered idle below this. Above it the panel is doing useful work
// and the AC charger stays out of the way.
#define SOLAR_ACTIVE_POWER     3.0    // solar above this = PV working -> AC OFF
#define SOLAR_IDLE_POWER       3.0    // solar below this = PV idle    -> AC may run
// AC charging hysteresis: once the battery reaches AC_STOP_SOC the charger is
// latched off and will NOT come back on - even with no sun - until the battery
// has fallen all the way to AC_START_SOC. That gives a proper deep cycle for
// the dataset instead of the charger topping up constantly.
#define AC_STOP_SOC           90.0    // AC charges up to here, then latches OFF
#define AC_START_SOC          30.0    // AC may only restart once SOC falls to here

// Solar cannot be limited by SOC without opening the MPPT relay, and cutting
// the controller's battery terminal makes it forget its settings. So this is
// left OFF: the MPPT stays connected and its own absorption/float stage limits
// the charge. To cap the maximum state of charge, lower the absorption voltage
// in the MPPT controller itself instead - that needs no relay switching.
#define ENABLE_PV_SOC_CUTOFF  false
#define PV_STOP_SOC           90.0    // solar charges up to here, then latches OFF
#define PV_START_SOC          45.0    // solar may only restart once SOC falls to here
#define SOURCE_SWITCH_DELAY   60000   // 60 s minimum between switches
#define SOLAR_PEAK_WINDOW_MS  120000   // remember the best solar reading for 2 min
#define SOURCE_CONFIRM_MS    180000   // condition must hold 3 min before switching

// Many relay modules are ACTIVE-LOW (IN pin LOW = relay energised).
// Driving the AC relay HIGH produced no click, so it is treated as active-low.
// If a relay ends up inverted, flip the matching line below.
#define AC_RELAY_ACTIVE_LOW   true
#define MAIN_RELAY_ACTIVE_LOW false


// ---------- WIFI ----------
#define WIFI_SSID      "YOUR_WIFI_SSID"
#define WIFI_PASS      "YOUR_WIFI_PASSWORD"

// ---------- RASPBERRY PI CONFIGURATION ----------
#define PI_HOSTNAME         "capstonepi.local"    // mDNS hostname
#define PI_PORT             5000                  // Flask server port
#define PI_API_ENDPOINT     "/api/data"           // main data endpoint
#define PI_HEALTH_ENDPOINT  "/health"             // health check (optional)
#define PI_STATUS_ENDPOINT  "/api/status"         // status (optional)
#define PI_DASHBOARD        "/"                   // dashboard (optional)

// Full API URL is built in wifi_sender.cpp from the above:
//   http://capstonepi.local:5000/api/data

// ---------- TIMING ----------
#define SENSOR_INTERVAL_MS   2000    // Read + send every 2 seconds
#define DISPLAY_INTERVAL_MS  500     // Update OLED every 0.5 second

// ---------- FEATURE TOGGLES ----------
#define ENABLE_WIFI    true
#define ENABLE_OLED    true

// ---------- TESTING ----------
// Set true to bypass low-battery load cutoff (RULE 4) during bench testing.
// MUST set back to false before real deployment / data collection!
#define TESTING_BYPASS_LOAD_CUTOFF  false

#endif
