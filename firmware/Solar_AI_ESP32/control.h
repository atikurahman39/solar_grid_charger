#ifndef CONTROL_H
#define CONTROL_H

#include <Arduino.h>

void initControl();
void applySafetyRules();      // rule-based AI protection
void manageChargingSource();  // solar-priority / AC-backup switching
void applyCommand(const String& key, const String& value);  // dashboard -> hardware
void updateStatusLEDs(bool wifiConnected);
void beep(int ms);
bool isButtonPressed();

#endif
