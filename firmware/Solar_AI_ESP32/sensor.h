#ifndef SENSOR_H
#define SENSOR_H

#include <Arduino.h>

// Holds all sensor readings + calculated values
struct SensorData {
    float solarVoltage;
    float solarCurrent;
    float solarPower;
    float batteryVoltage;
    float batteryCurrent;
    float batteryPower;
    float batteryTemperature;
    float chargeVoltage;    // INA237 on C+ : voltage the charger is delivering
    float chargeCurrent;    // INA237 on C+ : total charging current entering battery
    float chargePower;
    float acCurrent;        // AC charger's share of the charging current
    float loadCurrent;
    float loadPower;
    float soc;
    bool  relayState;
    bool  acRelayState;     // AC charger relay on/off
    String chargingSource;  // "Solar", "Grid", "Both", "None"
    bool  mosfet1State;     // Fan
    bool  mosfet2State;     // Bulb1
    bool  mosfet3State;     // Bulb2
    int   loadLevel;        // 0-7 (binary combination of 3 loads)
    String systemState;     // Charging or Discharging
    float energyHarvested;
    bool  overTempLatched;  // true while the over-temp latch is engaged (50C -> until 35C)
};

extern SensorData sensorData;

bool initSensors();
bool readSensors();
void resetSOC(float startSOC);

// Grid current (measured) + solar contribution (estimated), in amps.
// Internal helper - not part of the JSON payload.
float getTotalChargeCurrent();

#endif
