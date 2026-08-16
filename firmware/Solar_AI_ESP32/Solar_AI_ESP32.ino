// =====================================================
//  Intelligent Hybrid Solar-Grid Charger
//  with IoT Monitoring and AI Battery Protection
//
//  ESP32 Main Firmware
//  Modular architecture — see individual .cpp files
//
//  Data flow:
//    Sensors -> Rule-based AI -> OLED + WiFi(Pi)
//
//  EEE Capstone Project
// =====================================================

#include "config.h"
#include "sensor.h"
#include "control.h"
#include "display.h"
#include "wifi_sender.h"

// Timing
unsigned long lastSensorTime  = 0;
unsigned long lastDisplayTime = 0;
bool wifiOK = false;

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(1000);
    Serial.println();
    Serial.println("=======================================");
    Serial.println(PROJECT_NAME);
    Serial.println("=======================================");

    // 1. Control pins first (safe states)
    initControl();
    Serial.println("[1/4] Control initialized");

    // 2. OLED display
#if ENABLE_OLED
    if (initDisplay()) {
        showBootScreen();
        Serial.println("[2/4] Display OK");
    } else {
        Serial.println("[2/4] Display FAILED");
    }
#endif

    // 3. Sensors
    if (initSensors()) {
        Serial.println("[3/4] Sensors OK");
    } else {
        Serial.println("[3/4] Sensor ERROR - check wiring");
        // blink red LED to signal error
        for (int i = 0; i < 5; i++) {
            digitalWrite(LED_RED, HIGH); delay(200);
            digitalWrite(LED_RED, LOW);  delay(200);
        }
    }

    // 4. WiFi
#if ENABLE_WIFI
    wifiOK = initWiFi();
    if (wifiOK) {
        Serial.println("[4/4] WiFi OK");
        beep(50); delay(60); beep(50);   // double beep = ready
    } else {
        Serial.println("[4/4] WiFi offline - local only");
    }
#endif

    Serial.println("=======================================");
    Serial.println("System running. Collecting data...");
    Serial.println("=======================================");
}

void loop() {
    unsigned long now = millis();

    // ---------- SENSOR READ + PROCESS (every 2s) ----------
    if (now - lastSensorTime >= SENSOR_INTERVAL_MS) {
        lastSensorTime = now;

        // 1. Read all sensors
        readSensors();

        // 2. Apply rule-based safety AI
        applySafetyRules();
        manageChargingSource();

        // 3. Update status LEDs
        updateStatusLEDs(wifiOK);

        // 4. Send to Raspberry Pi via WiFi
#if ENABLE_WIFI
        wifiOK = isWiFiConnected();
        if (wifiOK) {
            digitalWrite(LED_BLUE, HIGH);       // blue = transmitting
            bool sent = sendDataToPi();
            digitalWrite(LED_BLUE, LOW);
            if (sent) Serial.println(">> Data sent to Pi");
        } else {
            // try reconnect occasionally
            wifiOK = initWiFi();
        }
#endif

        // 5. Print to Serial (debug)
        if (sensorData.soc < 0) {
            Serial.printf("PV:%.1fV %.2fA | BAT:%.1fV %.2fA | T:%.1fC | SOC:N/A (no battery) | %s\n",
                          sensorData.solarVoltage, sensorData.solarCurrent,
                          sensorData.batteryVoltage, sensorData.batteryCurrent,
                          sensorData.batteryTemperature,
                          sensorData.systemState.c_str());
        } else {
            Serial.printf("PV:%.1fV %.2fA | BAT:%.1fV %.2fA | T:%.1fC | SOC:%.0f%% | %s\n",
                          sensorData.solarVoltage, sensorData.solarCurrent,
                          sensorData.batteryVoltage, sensorData.batteryCurrent,
                          sensorData.batteryTemperature, sensorData.soc,
                          sensorData.systemState.c_str());
        }
    }

    // ---------- DISPLAY UPDATE (every 0.5s) ----------
#if ENABLE_OLED
    if (now - lastDisplayTime >= DISPLAY_INTERVAL_MS) {
        lastDisplayTime = now;
        updateDisplay(wifiOK);
    }
#endif

    // ---------- BUTTON CHECK ----------
    if (isButtonPressed()) {
        // Manual override: reset SOC to 100% (use when battery known full)
        resetSOC(100.0);
        beep(200);
        Serial.println("Button pressed: SOC reset to 100%");
        delay(300);   // debounce
    }
}
