#include "wifi_sender.h"
#include "config.h"
#include "sensor.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>   // parse command from the Pi POST response
#include "control.h"       // applyCommand()

// Build the full API URL from config.h parts
static String buildApiUrl() {
    return "http://" + String(PI_HOSTNAME) + ":" +
           String(PI_PORT) + String(PI_API_ENDPOINT);
}

bool initWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    Serial.print("Connecting to WiFi");
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 30) {
        delay(500);
        Serial.print(".");
        tries++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.print("WiFi connected. IP: ");
        Serial.println(WiFi.localIP());
        Serial.print("Sending data to: ");
        Serial.println(buildApiUrl());
        return true;
    } else {
        Serial.println("WiFi connection FAILED - running offline");
        return false;
    }
}

bool isWiFiConnected() {
    return WiFi.status() == WL_CONNECTED;
}

bool sendDataToPi() {
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    HTTPClient http;
    http.begin(buildApiUrl());
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(3000);

    // Battery current: Pi validator only accepts 0 to 20 (no negatives).
    // We send the absolute value so discharge readings are not rejected.
    // The system_state field tells whether it is charging or discharging.
    float batCurrentAbs = sensorData.batteryCurrent;
    if (batCurrentAbs < 0) batCurrentAbs = -batCurrentAbs;

    // Battery power as magnitude as well, so the dashboard shows a positive
    // figure. Direction (charging vs discharging) is carried by system_state.
    float batPowerAbs = sensorData.batteryPower;
    if (batPowerAbs < 0) batPowerAbs = -batPowerAbs;

    // Build JSON - every measurement and state the node has.
    // Powers are sent as measured here; the Pi is free to recompute them.
    String json = "{";
    // --- solar side (INA238 @ 0x41) ---
    json += "\"solar_voltage\":"        + String(sensorData.solarVoltage, 2)      + ",";
    json += "\"solar_current\":"        + String(sensorData.solarCurrent, 3)      + ",";
    json += "\"solar_power\":"          + String(sensorData.solarPower, 2)        + ",";
    // --- battery / discharge side (INA238 @ 0x40) ---
    json += "\"battery_voltage\":"      + String(sensorData.batteryVoltage, 2)    + ",";
    json += "\"battery_current\":"      + String(batCurrentAbs, 3)                + ",";
    json += "\"battery_power\":"        + String(batPowerAbs, 2)                 + ",";
    json += "\"battery_temperature\":"  + String(sensorData.batteryTemperature, 1)+ ",";
    json += "\"soc\":"                  + String(sensorData.soc, 1)               + ",";
    // --- charge line (INA237 @ 0x44) ---
    json += "\"charge_voltage\":"       + String(sensorData.chargeVoltage, 2)     + ",";
    json += "\"charge_current\":"       + String(sensorData.chargeCurrent, 3)     + ",";
    json += "\"charge_power\":"         + String(sensorData.chargePower, 2)       + ",";
    json += "\"ac_current\":"           + String(sensorData.acCurrent, 3)         + ",";
    // --- load ---
    json += "\"load_current\":"         + String(sensorData.loadCurrent, 3)       + ",";
    json += "\"load_power\":"           + String(sensorData.loadPower, 2)         + ",";
    json += "\"load_level\":"           + String(sensorData.loadLevel)            + ",";
    json += "\"mosfet1_state\":"        + String(sensorData.mosfet1State ? 1 : 0) + ",";
    json += "\"mosfet2_state\":"        + String(sensorData.mosfet2State ? 1 : 0) + ",";
    json += "\"mosfet3_state\":"        + String(sensorData.mosfet3State ? 1 : 0) + ",";
    // --- switching / state ---
    json += "\"relay_state\":"          + String(sensorData.relayState ? 1 : 0)   + ",";
    json += "\"ac_relay_state\":"       + String(sensorData.acRelayState ? 1 : 0) + ",";
    json += "\"charging_source\":\""    + sensorData.chargingSource               + "\",";
    json += "\"system_state\":\""       + sensorData.systemState                  + "\",";
    // --- energy + node health ---
    json += "\"energy_harvested\":"     + String(sensorData.energyHarvested, 3)   + ",";
    json += "\"uptime_s\":"             + String(millis() / 1000)                 + ",";
    json += "\"wifi_rssi\":"            + String(WiFi.RSSI())                     + ",";
    json += "\"free_heap\":"            + String(ESP.getFreeHeap());
    json += "}";

    int code = http.POST(json);

    // Read the response body BEFORE http.end(). The Pi returns any pending
    // dashboard command inside a "command" object, e.g.
    //   {"status":"success", ... ,"command":{"mosfet1":"ON","grid_relay":"OFF"}}
    // command is null when nothing is queued.
    String resp = http.getString();
    http.end();

    if (code == 200) {
        // Parse and apply any command. A parse failure or a null command is
        // simply ignored - it must never disturb normal telemetry.
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, resp);
        if (!err) {
            JsonObject cmd = doc["command"].as<JsonObject>();
            if (!cmd.isNull()) {
                for (JsonPair kv : cmd) {
                    const char* val = kv.value().as<const char*>();
                    if (val) {
                        applyCommand(String(kv.key().c_str()), String(val));
                    }
                }
            }
        }
        return true;
    } else {
        Serial.print("POST failed, code: ");
        Serial.println(code);
        return false;
    }
}
