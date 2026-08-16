#include "display.h"
#include "config.h"
#include "sensor.h"
#include <U8g2lib.h>
#include <SPI.h>

// SSD1309 128x64 over hardware SPI
// Constructor params: rotation, CS, DC, RST
U8G2_SSD1309_128X64_NONAME0_F_4W_HW_SPI u8g2(U8G2_R0, OLED_CS, OLED_DC, OLED_RST);

bool initDisplay() {
    // U8g2 uses hardware SPI on default VSPI pins (SCK=18, MOSI=23)
    u8g2.begin();
    u8g2.setBusClock(4000000);   // 4MHz — stable for SSD1309
    return true;
}

void showBootScreen() {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_ncenB08_tr);
    u8g2.drawStr(0, 12, "Solar AI Charger");
    u8g2.drawStr(0, 26, "v1.0 Starting...");
    u8g2.drawStr(0, 44, "Capstone Project");
    u8g2.drawStr(0, 58, "Initializing...");
    u8g2.sendBuffer();
}

void updateDisplay(bool wifiConnected) {
    u8g2.clearBuffer();
    char buf[32];

    // ---------- title bar (inverted) ----------
    u8g2.drawBox(0, 0, 128, 11);
    u8g2.setDrawColor(0);
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(2, 8, "SOLAR AI");
    u8g2.drawStr(46, 8, sensorData.chargingSource.c_str());   // Solar/Grid/Both/None

    bool faulty = sensorData.overTempLatched ||
                  (sensorData.batteryVoltage > 14.6);
    u8g2.drawStr(faulty ? 88 : 96, 8, faulty ? "FAULT" : (wifiConnected ? "LINK" : "----"));
    u8g2.setDrawColor(1);

    // ---------- the three measurement points ----------
    // Same shape for each: where, what voltage, what current.
    u8g2.setFont(u8g2_font_6x10_tr);
    snprintf(buf, sizeof(buf), "PV %5.1fV %5.2fA",
             sensorData.solarVoltage, sensorData.solarCurrent);
    u8g2.drawStr(0, 21, buf);

    snprintf(buf, sizeof(buf), "BT %5.1fV %5.2fA",
             sensorData.batteryVoltage, sensorData.batteryCurrent);
    u8g2.drawStr(0, 31, buf);

    snprintf(buf, sizeof(buf), "IN %5.1fV %5.2fA",
             sensorData.chargeVoltage, sensorData.chargeCurrent);
    u8g2.drawStr(0, 41, buf);

    // ---------- state of charge bar ----------
    const int barX = 0, barY = 44, barW = 92, barH = 10;
    u8g2.drawFrame(barX, barY, barW, barH);
    if (sensorData.soc >= 0) {
        int fill = (int)((barW - 4) * sensorData.soc / 100.0 + 0.5);
        if (fill > 0) u8g2.drawBox(barX + 2, barY + 2, fill, barH - 4);
        snprintf(buf, sizeof(buf), "%3.0f%%", sensorData.soc);
    } else {
        snprintf(buf, sizeof(buf), "N/A");
    }
    u8g2.drawStr(barX + barW + 4, barY + 9, buf);

    // ---------- bottom status ----------
    u8g2.setFont(u8g2_font_5x8_tr);
    snprintf(buf, sizeof(buf), "%-11s L%d  %2.0fC",
             sensorData.systemState.c_str(),
             sensorData.loadLevel,
             sensorData.batteryTemperature);
    u8g2.drawStr(0, 63, buf);

    u8g2.sendBuffer();
}
