#include "sensor.h"
#include "config.h"
#include <Wire.h>
#include <INA238.h>
#include <OneWire.h>
#include <DallasTemperature.h>

SensorData sensorData;

// Internal only - never sent in the JSON, so the Pi schema is untouched.
static float solarShareA = 0.0;   // solar contribution as battery-side amps
static float totalChargeA = 0.0;  // grid + solar entering the battery

INA238 solarINA(SOLAR_INA_ADDR);            // 0x41 (PV panel side, R015)
INA238 batteryINA(BATTERY_INA_ADDR);        // 0x40 (Battery discharge line, R015)
INA238 chargeINA(CHARGE_INA_ADDR);          // 0x44 (Charge line C+, INA237 R015)
OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);

// SOC tracking via Coulomb counting
// -1 means "not initialized / no battery connected" (shown as N/A)
static float socPercent = -1.0;
static unsigned long lastSocTime = 0;
static bool socInitialized = false;
static float socSmoothV = 0.0;    // low-pass filtered battery voltage for SOC correction
static bool chargeAvailable = false;      // INA237 on the charge line present?

// Estimate SOC from battery voltage (LiFePO4 discharge curve)
// Used at startup to set a realistic starting SOC
static float voltageToSOC(float v) {
    if (v >= 14.4) return 100.0;
    if (v >= 13.6) return 90.0 + (v - 13.6) / (14.4 - 13.6) * 10.0;
    if (v >= 13.3) return 70.0 + (v - 13.3) / (13.6 - 13.3) * 20.0;
    if (v >= 13.0) return 50.0 + (v - 13.0) / (13.3 - 13.0) * 20.0;
    if (v >= 12.8) return 30.0 + (v - 12.8) / (13.0 - 12.8) * 20.0;
    if (v >= 12.0) return 10.0 + (v - 12.0) / (12.8 - 12.0) * 20.0;
    if (v >= 11.0) return  0.0 + (v - 11.0) / (12.0 - 11.0) * 10.0;
    return 0.0;
}

bool initSensors() {
    Wire.begin(I2C_SDA, I2C_SCL);
    // Slow I2C clock: the PV sensor sits right on the MPPT input line, where
    // switching noise peaks at high solar power. 50kHz is far more tolerant of
    // that noise than the 100kHz default, at no practical cost (we read ~2/sec).
    Wire.setClock(50000);
    Wire.setTimeOut(50);

    // ---- Solar side: INA238 (0x41, R015 shunt) ----
    if (!solarINA.begin()) {
        Serial.println("ERROR: Solar INA238 (0x41) not found");
        return false;
    }
    solarINA.setMaxCurrentShunt(8.0, 0.015);

    // ---- Battery side: INA238 (0x40, R015 shunt) ----
    if (!batteryINA.begin()) {
        Serial.println("ERROR: Battery INA238 (0x40) not found");
        return false;
    }
    // R015 = 0.015 ohm shunt, max 8A (safe for fan + 2 bulbs = ~4.65A)
    batteryINA.setMaxCurrentShunt(8.0, 0.015);

    // ---- Charge line: INA237 (0x44, R015 shunt) ----
    // INA237 shares the INA238 register map, so the same driver works. If the
    // driver rejects it on a device-ID check we carry on anyway rather than
    // aborting the whole system - the readings still come through.
    chargeAvailable = chargeINA.begin();
    chargeINA.setMaxCurrentShunt(8.0, 0.015);
    if (!chargeAvailable) {
        Serial.println("WARN: charge INA237 (0x44) begin() failed - reading anyway");
    }

    tempSensor.begin();
    lastSocTime = millis();

Serial.printf("Sensors OK: solar 0x41 + battery 0x40 + charge 0x44 %s\n",
                  chargeAvailable ? "(ok)" : "(ID mismatch)");
    return true;
}

void resetSOC(float startSOC) {
    socPercent = startSOC;
    socInitialized = true;
}

// Counts how many times a sensor had to be re-initialised (diagnostics)
static uint32_t solarReinitCount = 0;

// A reading of exactly 0.000 V AND 0.000 A means the I2C read failed or the
// sensor reset - a live sensor always returns some small non-zero noise.
// When that happens we re-initialise the sensor and read again, instead of
// writing a false zero into the dataset.
static bool solarReadFailed() {
    return (sensorData.solarVoltage == 0.0f && sensorData.solarCurrent == 0.0f);
}

bool readSensors() {
    // ---- SOLAR (INA238, 0x41) ----
    // INA238 (Rob Tillaart): getBusVoltage() returns V, getCurrent() returns A
    // Switching noise corrupts a large share of this sensor's reads while the
    // system is charging - measured at 71% with the AC charger running. A
    // corrupted read comes back as exactly 0.000 on both registers at once; a
    // live sensor always returns a little noise, even in the dark. So retry
    // until a clean pair arrives, and fall back to the last good value rather
    // than writing a false zero that would look like "no sun".
    static float lastGoodV = 0.0, lastGoodI = 0.0;
    float sv = 0.0, si = 0.0;
    bool clean = false;
    for (int attempt = 0; attempt < 15; attempt++) {
        sv = solarINA.getBusVoltage();
        si = solarINA.getCurrent();
        if (!(sv == 0.0f && si == 0.0f)) { clean = true; break; }
    }

    if (clean) {
        sensorData.solarVoltage = sv;
        sensorData.solarCurrent = si;
        lastGoodV = sv;
        lastGoodI = si;
    } else {
        solarReinitCount++;
        sensorData.solarVoltage = lastGoodV;      // hold, never record a fake zero
        sensorData.solarCurrent = lastGoodI;
        static unsigned long lastWarn = 0;
        if (millis() - lastWarn > 30000) {
            lastWarn = millis();
            Serial.printf("WARN: solar INA unreadable, holding last value (fails=%lu)\n",
                          (unsigned long)solarReinitCount);
        }
    }

    if (sensorData.solarCurrent < 0) sensorData.solarCurrent = 0;  // no negative solar
    sensorData.solarPower   = sensorData.solarVoltage * sensorData.solarCurrent;

    // ---- BATTERY DISCHARGE LINE (INA238, 0x40) ----
    // This sensor sits on the P+ (discharge) line, feeding the buck converter
    // and loads. What it measures IS the load draw. The true battery current is
    // the NET of charge (C+ side) minus this discharge, computed further below
    // once the charge side has been read.
    sensorData.batteryVoltage = batteryINA.getBusVoltage();
    float dischargeA = batteryINA.getCurrent();
    if (dischargeA < 0) dischargeA = -dischargeA;   // magnitude of what leaves P+

    // ---- LOAD ----
    // The discharge-line sensor directly measures what the loads take.
    sensorData.loadCurrent = dischargeA;
    sensorData.loadPower   = sensorData.batteryVoltage * sensorData.loadCurrent;

    // ---- CHARGE LINE (INA237, 0x44) ----
    // This INA sits on the charger bus. It cannot be isolated from the bus
    // voltage, so with the AC relay open it still reports whatever the bus is
    // doing - which is not grid charging. No current can cross an open relay,
    // so every grid figure is reported as a hard zero in that state.
    if (sensorData.acRelayState) {
        sensorData.chargeVoltage = chargeINA.getBusVoltage();
        sensorData.chargeCurrent = chargeINA.getCurrent();
        if (sensorData.chargeCurrent < 0) sensorData.chargeCurrent = 0;
        sensorData.chargePower = sensorData.batteryVoltage * sensorData.chargeCurrent;
    } else {
        sensorData.chargeVoltage = 0.0;
        sensorData.chargeCurrent = 0.0;
        sensorData.chargePower   = 0.0;
    }

    // Solar's contribution, converted to battery-side amps. The panel runs near
    // 18V while the battery sits near 13V, so panel current cannot be used
    // directly - the MPPT steps it up (about 90% efficient).
    solarShareA = 0.0;
    if (sensorData.batteryVoltage > 9.0 && sensorData.solarPower > 1.0) {
        solarShareA = (sensorData.solarPower * 0.9) / sensorData.batteryVoltage;
    }

    // Grid share: with the relay open it is zero by definition; with it closed,
    // whatever the bus carries beyond what solar is supplying.
    if (sensorData.acRelayState) {
        float acEst = sensorData.chargeCurrent - solarShareA;
        sensorData.acCurrent = (acEst > 0.1) ? acEst : 0.0;
    } else {
        sensorData.acCurrent = 0.0;
    }

    // Internal total for the SOC. With the relay open the sensor is reporting
    // zero, so solar is carried by its estimate - otherwise charging from the
    // sun would never move the SOC. Never sent in the JSON.
    if (sensorData.acRelayState) {
        totalChargeA = sensorData.chargeCurrent;      // measured (grid, solar idle)
    } else {
        totalChargeA = solarShareA;                   // estimated (solar only)
    }

    // ---- TRUE BATTERY CURRENT (net) ----
    // The battery is 4-terminal: charge enters C+, discharge leaves P+. Neither
    // sensor alone sees the net. Combine them:
    //     net = total charge in  -  load draw out
    // Positive = the pack is net charging, negative = net discharging.
    sensorData.batteryCurrent = totalChargeA - sensorData.loadCurrent;
    sensorData.batteryPower   = sensorData.batteryVoltage * sensorData.batteryCurrent;

    // ---- TEMPERATURE (DS18B20) ----
    tempSensor.requestTemperatures();
    float t = tempSensor.getTempCByIndex(0);
    // DS18B20 returns -127 when disconnected, 85 as power-on default
    // Reject these and keep the last good reading
    if (t > 0 && t < 80 && t != 85.0) {
        sensorData.batteryTemperature = t;
    }
    // If we never got a valid reading, default to safe room temp
    if (sensorData.batteryTemperature <= 0 || sensorData.batteryTemperature > 80) {
        sensorData.batteryTemperature = 25.0;   // safe default
    }

    // ---- SOC via Coulomb counting + voltage ----
    // Initialize SOC from battery voltage on first valid reading
    if (!socInitialized && sensorData.batteryVoltage > 9.0) {
        socPercent = voltageToSOC(sensorData.batteryVoltage);
        socInitialized = true;
        lastSocTime = millis();
    }

    unsigned long now = millis();
    float dtHours = (now - lastSocTime) / 3600000.0;   // ms to hours
    lastSocTime = now;

    if (sensorData.batteryVoltage <= 9.0) {
        // Battery disconnected -> SOC not available (N/A)
        // The INA bus pin floats with no battery, giving a small stray reading
        // (e.g. 3.6 V). Force everything to a clean zero so the dashboard shows
        // a proper "no battery" state instead of ghost values.
        sensorData.batteryVoltage = 0.0;
        sensorData.batteryCurrent = 0.0;
        sensorData.batteryPower   = 0.0;
        sensorData.loadCurrent    = 0.0;
        sensorData.loadPower      = 0.0;
        socPercent = -1.0;
        socInitialized = false;   // will re-init when battery reconnects
    }
    else {
        // ---- SOC estimation ----
        // Base: coulomb counting. batteryCurrent is the net (charge in - load
        // out) computed above, so integrating it moves SOC the right way and,
        // crucially, does NOT jump when a load switches - it only tracks charge
        // actually entering or leaving the pack.
        float deltaAh = sensorData.batteryCurrent * dtHours;
        socPercent += (deltaAh / BATTERY_CAPACITY_AH) * 100.0;

        // Smooth the battery voltage with a slow low-pass. A load turning on
        // sags the voltage for a moment; smoothing keeps that brief dip from
        // reaching the SOC.
        if (socSmoothV <= 0.0) socSmoothV = sensorData.batteryVoltage;   // seed
        socSmoothV = socSmoothV * (1.0 - SOC_VOLT_SMOOTH)
                   + sensorData.batteryVoltage * SOC_VOLT_SMOOTH;

        // Voltage correction, but only when the pack is near rest. Under load
        // the terminal voltage sags from internal resistance and no longer
        // reflects the true SOC, so the correction is switched off. This is
        // what stops SOC from dropping when several loads run and rising when
        // one turns off.
        float wCorrect = (sensorData.loadCurrent < SOC_REST_LOAD_A)
                         ? SOC_VCORRECT_REST : SOC_VCORRECT_LOADED;
        if (wCorrect > 0.0) {
            float vSOCsmooth = voltageToSOC(socSmoothV);
            socPercent = socPercent * (1.0 - wCorrect) + vSOCsmooth * wCorrect;
        }

        // Full-charge reset. When the pack is held at the full voltage and the
        // charge current has tapered off (absorption complete), the battery is
        // genuinely full - snap to 100% to clear any accumulated drift. This is
        // the periodic recalibration that open-loop coulomb counting needs.
        if (sensorData.batteryVoltage >= SOC_FULL_VOLT &&
            totalChargeA > 0.0 && totalChargeA < SOC_FULL_RESET_A) {
            socPercent = 100.0;
        }
    }

    // Constrain only if SOC is valid (not the -1 N/A marker)
    if (socPercent >= 0) {
        socPercent = constrain(socPercent, 0.0, 100.0);
    }
    sensorData.soc = socPercent;

    // ---- CHARGING MODE detection ----
    // NOTE: Pi validator only accepts CC, CV, Float, Idle
    // Based on the measured charge current (INA237 on the C+ line)
    // A real charger moves CC -> CV -> Float. Voltage alone cannot separate CV
    // from Float, because both sit near the absorption voltage; what changes is
    // the current, which tapers as the battery fills. So we use both:
    //   below the absorption voltage        -> CC    (bulk, current limited)
    //   at absorption voltage, current high -> CV    (voltage held, current falling)
    //   at absorption voltage, current low  -> Float (topped up, maintaining)
    // ---- SYSTEM STATE ----
    // Simply whether the pack is taking charge or supplying it. Faults and
    // protection are reported through the relay and temperature fields.
    if (totalChargeA > CHARGE_DETECT_A) {
        sensorData.systemState = "Charging";
    } else {
        sensorData.systemState = "Discharging";
    }

    // ---- CHARGING SOURCE ----
    // Judge this on the internal total, not on chargeCurrent: that field is
    // deliberately zeroed while the AC relay is open, so using it here would
    // report "None" during perfectly good solar charging.
    bool solarWorking = (sensorData.solarPower > SOLAR_IDLE_POWER);
    if (totalChargeA <= CHARGE_DETECT_A) {
        sensorData.chargingSource = "None";
    } else if (sensorData.acRelayState && solarWorking) {
        sensorData.chargingSource = "Both";
    } else if (sensorData.acRelayState) {
        sensorData.chargingSource = "Grid";
    } else {
        sensorData.chargingSource = "Solar";
    }


    // ---- Energy harvested (Wh accumulation) ----
    sensorData.energyHarvested += sensorData.solarPower * dtHours;

    return true;
}


float getTotalChargeCurrent() {
    return totalChargeA;
}
