#pragma once
// Copy to config.h (ignored by Git). Replace before flashing.
// WPA2 AP password must be 8 or more characters.
#define TAXILE_AP_SSID "Taxile-Ram"
#define TAXILE_AP_PASSWORD "CHANGE-ME-1234"
// Leave empty to disable station connection/NTP.
#define TAXILE_WIFI_SSID ""
#define TAXILE_WIFI_PASSWORD ""
// Millisecond sample period. OBD read latency may make actual intervals longer.
#define TAXILE_SAMPLE_MS 2000
#define TAXILE_IDLE_END_MS 180000
