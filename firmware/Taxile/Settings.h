#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>

struct Settings {
  String ssid, password, endpoint, token, ca, admin;
  double calibration = 1;
  bool allowHttp = false;
  bool load() {
    Preferences p;
    if (!p.begin("taxile", false)) return false;
    String json = p.getString("config", "{}");
    DynamicJsonDocument d(8192);
    if (deserializeJson(d, json)) { p.end(); return false; }
    ssid = d["ssid"] | ""; password = d["password"] | "";
    endpoint = d["endpoint"] | ""; token = d["token"] | "";
    ca = d["ca"] | ""; allowHttp = d["allow_http"] | false;
    calibration = d["calibration"] | 1.0;
    admin = p.getString("admin", "");
    if (admin.length() < 16) {
      char b[25]; snprintf(b, sizeof(b), "%08lx%08lx%08lx",
        (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
      admin = b;
      if (!p.putString("admin", admin)) { p.end(); return false; }
    }
    p.end(); return true;
  }
  bool save(const String& json) {
    Preferences p;
    if (!p.begin("taxile", false)) return false;
    bool ok = p.putString("config", json) == json.length();
    p.end(); return ok;
  }
};
