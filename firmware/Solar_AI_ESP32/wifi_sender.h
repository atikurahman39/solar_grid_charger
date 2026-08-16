#ifndef WIFI_SENDER_H
#define WIFI_SENDER_H

#include <Arduino.h>

bool initWiFi();
bool isWiFiConnected();
bool sendDataToPi();      // POST sensor JSON to Raspberry Pi

#endif
