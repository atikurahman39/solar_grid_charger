#include "control.h"
#include "config.h"
#include "sensor.h"

// Forward declarations (definitions live further down)
static void setMainRelay(bool on);
static void setACRelay(bool on);

// Load scheduling
static unsigned long lastLoadChange = 0;
static unsigned long bootTime = 0;
static unsigned long nextChangeInterval = 60000;  // current random interval
static int currentLoadLevel = 7;          // start with ALL loads on
static bool startupPhase = true;          // first minute: all loads on
static bool lowBatteryLatch = false;      // true once SOC hit cutoff, until recovery
static bool overTempLatch   = false;      // true once temp hit TEMP_MAX, until it cools to TEMP_RECOVERY

// Over-temperature with hysteresis:
//   - trips true when temperature reaches TEMP_MAX (50C)
//   - stays true (latched) even as it falls, until it cools to TEMP_RECOVERY (35C)
// This stops the relay from chattering on/off around the 50C line.
static bool isOverTemp() {
    if (sensorData.batteryTemperature >= TEMP_MAX) {
        overTempLatch = true;                       // trip and latch
    } else if (sensorData.batteryTemperature <= TEMP_RECOVERY) {
        overTempLatch = false;                      // cooled enough: release
    }
    // between TEMP_RECOVERY and TEMP_MAX the latch keeps its previous value
    sensorData.overTempLatched = overTempLatch;   // share it for display / telemetry
    return overTempLatch;
}

// ---------------------------------------------------------------------------
// DASHBOARD COMMAND STATE  (data collection is finished: the old random load
// cycling is removed; loads are now driven by the dashboard, capped by safety)
// ---------------------------------------------------------------------------
#define MODE_HYBRID 0      // auto: solar priority, AC backup (original behaviour)
#define MODE_SOLAR  1      // solar only: AC charger forced off
#define MODE_GRID   2      // grid: AC charger allowed on (still safety-limited)

static int  desiredLoad   = 0;      // bitmask the dashboard wants (bit0 Fan,1 Bulb1,2 Bulb2)
static int  cmdChargeMode = MODE_HYBRID;
static int  cmdGridManual = -1;     // manual AC relay override: -1 none, 0 OFF, 1 ON
static bool acCommandDirty = false; // a grid/mode command arrived -> apply without the confirm delay
#define STARTUP_ALL_ON_MS   60000         // 1 minute all loads on
// How long a load level runs depends on how heavy it is. Running all three
// loads together drains the battery fast, so that combination is kept short;
// a single light load may stay on much longer. This also mirrors real usage -
// a house rarely runs everything at once for half an hour.
#define LOAD_MIN_MS        300000         // light load: 5 min minimum
#define LOAD_MAX_MS       1800000         // light load: 30 min maximum
#define MED_LOAD_MIN_MS    300000         // two loads: 5 min
#define MED_LOAD_MAX_MS    900000         // two loads: 15 min
#define FULL_LOAD_MIN_MS   120000         // all three: 2 min
#define FULL_LOAD_MAX_MS   300000         // all three: 5 min

// How many of the three loads a level switches on.
static int loadsInLevel(int level) {
    int n = 0;
    if (level & 0x01) n++;
    if (level & 0x02) n++;
    if (level & 0x04) n++;
    return n;
}

// Pick a random level that uses no more than maxLoads outputs, and is
// different from the level we are already on.
static int randomLevelWithin(int maxLoads, int avoid) {
    int allowed[8];
    int count = 0;
    for (int lv = 0; lv <= 7; lv++) {
        if (loadsInLevel(lv) <= maxLoads && lv != avoid) allowed[count++] = lv;
    }
    if (count == 0) return 0;
    return allowed[random(0, count)];
}

// Pick how long the given load level should stay on.
static unsigned long pickLoadDuration(int level) {
    int active = 0;
    if (level & 0x01) active++;           // fan
    if (level & 0x02) active++;           // bulb1
    if (level & 0x04) active++;           // bulb2

    if (active >= 3) return random(FULL_LOAD_MIN_MS, FULL_LOAD_MAX_MS);
    if (active == 2) return random(MED_LOAD_MIN_MS,  MED_LOAD_MAX_MS);
    return random(LOAD_MIN_MS, LOAD_MAX_MS);
}

void initControl() {
    // Outputs
    pinMode(LED_GREEN,  OUTPUT);
    pinMode(LED_RED,    OUTPUT);
    pinMode(LED_BLUE,   OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(RELAY_PIN,  OUTPUT);
    pinMode(MOSFET1_PIN, OUTPUT);
    pinMode(MOSFET2_PIN, OUTPUT);
    pinMode(MOSFET3_PIN, OUTPUT);
    pinMode(AC_RELAY_PIN, OUTPUT);

    // Force buzzer OFF. Do NOT call noTone() here: on ESP32 tone() sets up an
    // LEDC channel on first use, so calling noTone() before any tone() prints
    // "LEDC is not initialized" errors.
    digitalWrite(BUZZER_PIN, LOW);

    // Input
    pinMode(BUTTON_PIN, INPUT_PULLUP);

    // Safe startup state
    setMainRelay(true);                // charging allowed
    digitalWrite(MOSFET1_PIN, LOW);
    digitalWrite(MOSFET2_PIN, LOW);
    digitalWrite(MOSFET3_PIN, LOW);
    setACRelay(false);                 // AC charger OFF at startup (polarity aware)
    digitalWrite(LED_GREEN,   LOW);
    digitalWrite(LED_RED,     LOW);
    digitalWrite(LED_BLUE,    LOW);

    sensorData.mosfet1State = false;
    sensorData.mosfet2State = false;
    sensorData.mosfet3State = false;
    sensorData.acRelayState = false;
    sensorData.chargingSource = "None";
    sensorData.loadLevel    = 0;

    // Data-collection phase is over: loads start OFF and are driven only by
    // dashboard commands (capped by the safety rules). No random cycling.
    bootTime = millis();
    lastLoadChange = millis();
    startupPhase = false;
    currentLoadLevel = 0;
    desiredLoad = 0;

    // AC relay self-test: click it once so wiring and polarity can be checked.
    // Listen for the click and watch the module LED - two seconds of AC
    // charging is harmless.
    Serial.println("AC relay self-test: switching ON for 2s...");
    setACRelay(true);
    delay(2000);
    setACRelay(false);
    Serial.println("AC relay self-test: OFF. (No click? flip AC_RELAY_ACTIVE_LOW in config.h)");

    // Startup beep
    beep(100);
    Serial.println("Ready: loads OFF, waiting for dashboard commands (safety active)");
}

// Set load level using 3-bit binary (0-7):
//   bit 0 (value 1) = Fan   (MOSFET1)
//   bit 1 (value 2) = Bulb1 (MOSFET2)
//   bit 2 (value 4) = Bulb2 (MOSFET3)
// Examples: 0=all off, 7=all on, 5=Fan+Bulb2, etc.
static void setLoadLevel(int level) {
    bool fan   = level & 0x01;   // bit 0
    bool bulb1 = level & 0x02;   // bit 1
    bool bulb2 = level & 0x04;   // bit 2

    digitalWrite(MOSFET1_PIN, fan   ? HIGH : LOW);
    digitalWrite(MOSFET2_PIN, bulb1 ? HIGH : LOW);
    digitalWrite(MOSFET3_PIN, bulb2 ? HIGH : LOW);

    sensorData.mosfet1State = fan;
    sensorData.mosfet2State = bulb1;
    sensorData.mosfet3State = bulb2;
    sensorData.loadLevel    = level;
}

// =====================================================
//  DASHBOARD COMMAND HANDLER
//  Called from wifi_sender when the Pi's POST response carries a command.
//  It only records the DESIRED state. applySafetyRules() and
//  manageChargingSource() decide whether it is actually allowed.
// =====================================================
void applyCommand(const String& key, const String& value) {
    bool on = value.equalsIgnoreCase("ON");

    if      (key == "mosfet1") { if (on) desiredLoad |= 0x01; else desiredLoad &= ~0x01; }
    else if (key == "mosfet2") { if (on) desiredLoad |= 0x02; else desiredLoad &= ~0x02; }
    else if (key == "mosfet3") { if (on) desiredLoad |= 0x04; else desiredLoad &= ~0x04; }
    else if (key == "grid_relay") {
        cmdGridManual  = on ? 1 : 0;   // manual override of the AC relay
        acCommandDirty = true;
    }
    else if (key == "charge_mode") {
        cmdGridManual  = -1;           // a mode selection reasserts policy control
        acCommandDirty = true;
        if      (value.equalsIgnoreCase("solar")) cmdChargeMode = MODE_SOLAR;
        else if (value.equalsIgnoreCase("grid"))  cmdChargeMode = MODE_GRID;
        else                                      cmdChargeMode = MODE_HYBRID;
    }
    else {
        Serial.printf("[CMD] unknown key ignored: %s\n", key.c_str());
        return;
    }
    Serial.printf("[CMD] %s = %s\n", key.c_str(), value.c_str());
}

// =====================================================
//  RULE-BASED AI - runs every cycle, protects hardware
// =====================================================
void applySafetyRules() {
    bool fault = false;

    // RULE 1: Over-temperature -> cut charging + all loads
    // Latched: trips at TEMP_MAX (50C), stays tripped until cooled to
    // TEMP_RECOVERY (35C), so it will not switch back on at 49.9C.
    if (isOverTemp()) {
        setMainRelay(false);
        setLoadLevel(0);
        fault = true;
        Serial.println("SAFETY: Over-temperature latch! Charging + loads OFF until cooled to 35C");
    }
    // RULE 2: Over-voltage -> cut charging
    else if (sensorData.batteryVoltage > 14.6) {
        setMainRelay(false);
        fault = true;
        Serial.println("SAFETY: Over-voltage! Charging OFF");
    }
    // RULE 3: Normal -> keep the MPPT path closed.
    // We deliberately never open this relay on SOC: cutting the MPPT's battery
    // connection makes the controller lose its settings and need reconfiguring.
    // A full battery is handled by switching the AC charger off instead, and
    // the MPPT's own charge controller stops the panel current by itself.
    else {
        // Solar charging window: charge to PV_STOP_SOC, then hold off until the
        // battery has discharged down to PV_START_SOC.
        static bool pvFullLatch = false;
        if (ENABLE_PV_SOC_CUTOFF) {
            if (sensorData.soc >= PV_STOP_SOC) pvFullLatch = true;
            if (sensorData.soc >= 0 && sensorData.soc < PV_START_SOC) pvFullLatch = false;
            setMainRelay(!pvFullLatch);
        } else {
            setMainRelay(true);
        }
    }

    // RULE 4: How much load the battery may carry.
    // The allowance depends on the state of charge AND on whether the battery
    // is currently being charged - while charging we can afford more load.
    //
    //   SOC < 20%              : everything off
    //   charging, 20-30%       : fan only
    //   charging, 30-60%       : at most two loads
    //   charging, above 60%    : anything, full load capped at 5 min
    //   discharging, below 30% : fan only
    //   discharging, above 30% : anything, full load capped at 5 min

    // Debounced charging flag. The raw current wobbles around the detection
    // threshold, and letting that flip the load allowance directly made the
    // scheduler re-pick a level every few seconds.
    static bool  chargingStable = false;
    static bool  chargingCandidate = false;
    static unsigned long chargingSince = 0;
    bool chargingNow = (getTotalChargeCurrent() > CHARGE_DETECT_A);
    if (chargingNow != chargingCandidate) {
        chargingCandidate = chargingNow;
        chargingSince = millis();
    } else if (chargingNow != chargingStable &&
               millis() - chargingSince > CHARGE_STATE_CONFIRM_MS) {
        chargingStable = chargingNow;
    }
    bool charging = chargingStable;

    float soc = sensorData.soc;

    // Cutoff latch with a small gap so a wobbling SOC cannot chatter the loads
    if (soc >= 0 && soc < SOC_LOW_CUTOFF) lowBatteryLatch = true;
    if (soc >= SOC_CUTOFF_CLEAR)          lowBatteryLatch = false;

    bool voltageTooLow = (sensorData.batteryVoltage < BATTERY_V_MIN);

    // Work out how many loads are allowed right now
    int maxLoads;
    if (TESTING_BYPASS_LOAD_CUTOFF) {
        maxLoads = 3;
    } else if (lowBatteryLatch || voltageTooLow || soc < 0) {
        maxLoads = 0;
    } else if (charging) {
        if (soc < SOC_REDUCED_LOAD)   maxLoads = 1;
        else if (soc < SOC_MID_ZONE)  maxLoads = 2;
        else                          maxLoads = 3;
    } else {
        maxLoads = (soc < SOC_REDUCED_LOAD) ? 1 : 3;
    }

    if (fault || isOverTemp()) maxLoads = 0;

    static int prevMaxLoads = -1;

    // -----------------------------------------------------------------
    // COMMAND-DRIVEN LOAD (replaces the old random cycling).
    // The dashboard sets desiredLoad; safety caps it here every cycle.
    //   * fault or over-temp        -> all loads off
    //   * otherwise cap to maxLoads -> shed Bulb2, then Bulb1, then Fan
    // When SOC recovers, maxLoads grows and the requested loads return
    // automatically on the next cycle. Safety always wins over the request.
    // -----------------------------------------------------------------
    int wanted = desiredLoad;
    if (fault || isOverTemp()) {
        wanted = 0;
    }
    // Shed loads (heaviest first) until within the allowance
    while (loadsInLevel(wanted) > maxLoads) {
        if      (wanted & 0x04) wanted &= ~0x04;   // drop Bulb2
        else if (wanted & 0x02) wanted &= ~0x02;   // drop Bulb1
        else if (wanted & 0x01) wanted &= ~0x01;   // drop Fan
        else break;
    }

    if (wanted != sensorData.loadLevel) {
        setLoadLevel(wanted);
        currentLoadLevel = wanted;
        Serial.printf("LOAD SET: level %d (requested %d, max %d, SOC %.1f%%)\n",
                      wanted, desiredLoad, maxLoads, soc);
    }

    prevMaxLoads = maxLoads;

    // Warning buzzer on high temp - beep occasionally, not every cycle
    static unsigned long lastBeepTime = 0;
    if (sensorData.batteryTemperature > TEMP_WARN &&
        sensorData.batteryTemperature <= TEMP_MAX) {
        if (millis() - lastBeepTime > 5000) {
            beep(50);
            lastBeepTime = millis();
        }
    }
}

// =====================================================
//  STATUS LEDs
// =====================================================
void updateStatusLEDs(bool wifiConnected) {
    digitalWrite(LED_GREEN, wifiConnected ? HIGH : LOW);

    bool fault = (isOverTemp()) ||
                 (sensorData.batteryVoltage > 14.6);
    digitalWrite(LED_RED, fault ? HIGH : LOW);

    // Blue handled during data transmit
}

void beep(int ms) {
    // A passive buzzer needs a frequency, not a steady HIGH. We generate the
    // square wave in software rather than with tone(): tone() drives the LEDC
    // peripheral, whose behaviour differs between ESP32 core versions and was
    // printing "LEDC is not initialized" at boot.
    unsigned long endAt = millis() + ms;
    while (millis() < endAt) {
        digitalWrite(BUZZER_PIN, HIGH);
        delayMicroseconds(250);          // 250us high + 250us low = 2 kHz
        digitalWrite(BUZZER_PIN, LOW);
        delayMicroseconds(250);
    }
    digitalWrite(BUZZER_PIN, LOW);
}

bool isButtonPressed() {
    return digitalRead(BUTTON_PIN) == LOW;
}




// =====================================================
//  CHARGING SOURCE MANAGEMENT
//  Solar has priority. The AC charger only runs while the
//  PV side is idle, so the two never push into the battery
//  at the same time.
//
//  Two solar thresholds give hysteresis: the AC charger is
//  cut once solar climbs past SOLAR_ACTIVE_POWER, and is
//  only allowed back once solar falls under SOLAR_IDLE_POWER.
//  Without that gap a passing cloud would chatter the relay.
// =====================================================
// Drive the main (MPPT) charging relay, honouring the module's polarity.
static void setMainRelay(bool on) {
#if MAIN_RELAY_ACTIVE_LOW
    digitalWrite(RELAY_PIN, on ? LOW : HIGH);
#else
    digitalWrite(RELAY_PIN, on ? HIGH : LOW);
#endif
    sensorData.relayState = on;
}

// Only one charging source may be connected to battery C+ at a time.
// Opening one relay before closing the other (break-before-make) stops the
// MPPT and the AC charger from ever pushing into the battery together.
static void applyChargingSource(bool useAC, bool faultActive);

// Drive the AC relay, honouring the module's polarity.
static void setACRelay(bool on) {
#if AC_RELAY_ACTIVE_LOW
    digitalWrite(AC_RELAY_PIN, on ? LOW : HIGH);
#else
    digitalWrite(AC_RELAY_PIN, on ? HIGH : LOW);
#endif
    sensorData.acRelayState = on;
}

static void applyChargingSource(bool useAC, bool faultActive) {
    // The MPPT path is left connected at all times (it is governed by the
    // safety rules only). Solar priority is handled by switching the AC
    // charger off whenever the panel is actually producing, so the two never
    // deliver current together in practice.
    (void)faultActive;
    setACRelay(useAC);
}

void manageChargingSource() {
    static unsigned long lastSwitch = 0;
    static unsigned long lastReport = 0;
    static unsigned long pendingSince = 0;
    static bool started = false;
    static bool pending = false;
    static bool pendingState = false;
    static bool firstDecision = true;

    if (!started) {
        setACRelay(false);                     // known state at boot
        lastSwitch = millis();
        started = true;
        return;
    }

    // ---- AC charge latch (hysteresis) ----
    static bool acFullLatch = false;
    float soc = sensorData.soc;
    if (soc >= AC_STOP_SOC)  acFullLatch = true;    // reached full -> lock out
    if (soc >= 0 && soc < AC_START_SOC) acFullLatch = false;  // drained -> allow again

    // ---- solar peak over a short window ----
    // Keeps the highest reading of the last SOLAR_PEAK_WINDOW_MS so that
    // intermittent sensor dropouts cannot be mistaken for nightfall.
    static float solarPeakW = 0.0;
    static unsigned long peakSince = 0;
    if (sensorData.solarPower > solarPeakW) solarPeakW = sensorData.solarPower;
    if (millis() - peakSince > SOLAR_PEAK_WINDOW_MS) {
        peakSince = millis();
        solarPeakW = sensorData.solarPower;      // start a fresh window
    }

    // ---- decide what the AC charger should be doing ----
    bool wantAC = sensorData.acRelayState;     // default: hold
    const char *reason = "holding";

    if (soc < 0) {
        wantAC = false;  reason = "no battery";
    }
    else if (isOverTemp() ||
             sensorData.batteryVoltage > 14.6) {
        wantAC = false;  reason = "fault";
    }
    else if (acFullLatch) {
        // Charged to AC_STOP_SOC earlier. Stay off - even with no sun - until
        // the battery drains back down to AC_START_SOC.
        wantAC = false;  reason = "charged, waiting for discharge";
    }
    else if (cmdGridManual != -1) {
        // Dashboard manual override of the AC relay. Safety checks above still
        // win (fault / no-battery / charged-full were handled before this).
        wantAC = (cmdGridManual == 1);
        reason = wantAC ? "manual: grid ON" : "manual: grid OFF";
    }
    else if (cmdChargeMode == MODE_SOLAR) {
        wantAC = false;  reason = "mode: solar only";
    }
    else if (cmdChargeMode == MODE_GRID) {
        wantAC = true;   reason = "mode: grid charging";
    }
    else if (solarPeakW > SOLAR_ACTIVE_POWER) {
        // HYBRID (auto): judged on the highest solar power seen in the last two
        // minutes, not this instant, so a single corrupted 0 W read cannot be
        // mistaken for nightfall.
        wantAC = false;  reason = "PV active";
    }
    else {
        // HYBRID: latch clear and panel idle, so top up from grid to AC_STOP_SOC.
        wantAC = true;   reason = "PV idle, charging to full";
    }

    // ---- heartbeat so the decision is never invisible ----
    if (millis() - lastReport > 30000) {
        lastReport = millis();
        Serial.printf("[AC] relay=%s want=%s (%s) solar=%.1fW peak=%.1fW SOC=%.1f%% charge=%.2fA\n",
                      sensorData.acRelayState ? "ON" : "OFF",
                      wantAC ? "ON" : "OFF", reason,
                      sensorData.solarPower, solarPeakW, soc, sensorData.chargeCurrent);
    }

    if (wantAC == sensorData.acRelayState) {   // nothing to change
        pending = false;
        acCommandDirty = false;
        return;
    }

    // Urgent conditions switch off immediately - they must not wait.
    bool urgent = (soc < 0) || (soc >= AC_STOP_SOC) ||
                  (isOverTemp()) ||
                  (sensorData.batteryVoltage > 14.6) ||
                  acCommandDirty;                 // dashboard command applies at once

    // The very first decision after boot is applied straight away, so the
    // system does not sit idle for minutes when it powers up at night.
    if (!urgent && !firstDecision) {
        if (millis() - lastSwitch < SOURCE_SWITCH_DELAY) return;   // anti-chatter

        if (!pending || pendingState != wantAC) {                  // start confirming
            pending = true;
            pendingState = wantAC;
            pendingSince = millis();
            Serial.printf("[AC] %s pending (%s) - confirming for %lus\n",
                          wantAC ? "ON" : "OFF", reason, SOURCE_CONFIRM_MS / 1000);
            return;
        }
        if (millis() - pendingSince < SOURCE_CONFIRM_MS) return;   // still settling
    }

    bool faultActive = (isOverTemp()) ||
                       (sensorData.batteryVoltage > 14.6);
    applyChargingSource(wantAC, faultActive);
    lastSwitch = millis();
    pending = false;
    firstDecision = false;
    acCommandDirty = false;
    Serial.printf("AC charger %s (%s) | solar %.1fW, SOC %.1f%%\n",
                  wantAC ? "ON" : "OFF", reason,
                  sensorData.solarPower, soc);
}

