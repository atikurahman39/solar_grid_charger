#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>

bool initDisplay();
void showBootScreen();
void updateDisplay(bool wifiConnected);

#endif
