/*
 * Taxile v0.1 - Freematics ONE+ ESP32 / 2018 Ram 1500.
 * Read-only OBD-II speed/RPM trip logger.
 * Requires official FreematicsPlus Arduino library.
 */
#include <Arduino.h>
#include <FreematicsPlus.h>
#include <SPI.h>
#include <SD.h>
#include <WiFi.h>
#include <WebServer.h>
#include <time.h>
#include "config.h"

#ifndef PID_SPEED
#define PID_SPEED 0x0D
#endif
#ifndef PID_RPM
#define PID_RPM 0x0C
#endif

static const char *LOG_PATH = "/taxile.csv";
static const uint32_t MAX_VALID_GAP_MS = 10000;
static const uint32_t RECONNECT_MS = 15000;
static const float MAX_SPEED_KPH = 220.0f;
static const double KM_TO_MILES = 0.62137119223733;
FreematicsESP32 sys;
COBD obd;
WebServer server(80);

bool sdReady = false;
bool obdReady = false;
bool tripActive = false;
bool previousSpeedValid = false;
bool clockValid = false;
int lastRPM = -1;
int lastSpeed = -1;
uint32_t lastSample = 0;
uint32_t lastSpeedAt = 0;
uint32_t lastEngineOnAt = 0;
uint32_t lastReconnect = 0;
uint32_t lastNtpAttempt = 0;
uint32_t bootId = 0;
uint32_t tripCounter = 0;
uint32_t tripId = 0;
uint32_t lastFlush = 0;
float previousKph = 0;
double tripMiles = 0;
File logFile;

uint32_t epochNow() {
  time_t now = time(nullptr);
  // 2024-01-01; reject unset ESP32 system clock.
  if (now >= 1704067200) {
    clockValid = true;
    return (uint32_t)now;
  }
  clockValid = false;
  return 0;
}

void openLog() {
  if (!sdReady || logFile) return;
  bool createHeader = !SD.exists(LOG_PATH);
  logFile = SD.open(LOG_PATH, FILE_APPEND);
  if (!logFile) { Serial.println("ERROR: cannot open CSV"); return; }
  if (createHeader) {
    logFile.println("event,boot_id,trip_id,epoch_utc,time_valid,uptime_ms,rpm,speed_kph,delta_miles,trip_miles");
    logFile.flush();
  }
}
void appendEvent(const char *event, double delta) {
  if (!sdReady) return;
  openLog();
  if (!logFile) return;
  uint32_t epoch = epochNow();
  logFile.printf("%s,%lu,%lu,%lu,%u,%lu,%d,%d,%.8f,%.8f\n",
    event, (unsigned long)bootId, (unsigned long)tripId,
    (unsigned long)epoch, epoch ? 1 : 0,
    (unsigned long)millis(), lastRPM, lastSpeed, delta, tripMiles);
  // Flush each event so unexpected power loss normally affects at most an in-progress line.
  logFile.flush();
}
void beginTrip() {
  tripActive = true;
  tripId = ++tripCounter;
  tripMiles = 0;
  previousSpeedValid = false;
  appendEvent("START", 0);
  Serial.printf("Trip %lu started\n", (unsigned long)tripId);
}
void endTrip() {
  if (!tripActive) return;
  appendEvent("END", 0);
  Serial.printf("Trip %lu ended, estimated %.3f miles\n", (unsigned long)tripId, tripMiles);
  tripActive = false;
  previousSpeedValid = false;
}
void setupWiFi() {
  WiFi.mode(WIFI_AP_STA);
  if (strlen(TAXILE_AP_PASSWORD) < 8) {
    Serial.println("ERROR: hotspot password too short, no hotspot started");
  } else {
    WiFi.softAP(TAXILE_AP_SSID, TAXILE_AP_PASSWORD);
    Serial.print("Hotspot IP: "); Serial.println(WiFi.softAPIP());
  }
  if (strlen(TAXILE_WIFI_SSID)) {
    WiFi.begin(TAXILE_WIFI_SSID, TAXILE_WIFI_PASSWORD);
    Serial.println("Connecting to configured Wi-Fi (nonblocking)");
  }
}
void clockUpdate() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (!clockValid && millis() - lastNtpAttempt > 30000) {
    lastNtpAttempt = millis();
    configTime(0, 0, "pool.ntp.org", "time.google.com");
  }
  epochNow();
}
String statusJSON() {
  String s = "{";
  s += "\"device\":\"Taxile-Ram\",";
  s += "\"obd_connected\":" + String(obdReady ? "true" : "false") + ",";
  s += "\"sd_ready\":" + String(sdReady ? "true" : "false") + ",";
  s += "\"trip_active\":" + String(tripActive ? "true" : "false") + ",";
  s += "\"speed_kph\":" + String(lastSpeed) + ",";
  s += "\"rpm\":" + String(lastRPM) + ",";
  s += "\"trip_miles\":" + String(tripMiles, 4) + ",";
  s += "\"utc_epoch\":" + String(epochNow()) + ",";
  s += "\"time_valid\":" + String(clockValid ? "true" : "false");
  s += "}";
  return s;
}
void configureServer() {
  server.on("/", HTTP_GET, []() {
    const char page[] = R"HTML(
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Taxile</title><style>body{font:16px system-ui;max-width:650px;margin:30px auto;padding:20px}button,a{display:inline-block;margin:8px;padding:10px;border:1px solid #999;border-radius:8px}pre{white-space:pre-wrap}</style></head>
<body><h1>Taxile</h1><p>2018 Ram 1500 - offline mileage prototype</p>
<pre id="data">Loading...</pre><button onclick="syncClock()">Sync clock from this device</button>
<a href="/log.csv">Download CSV</a>
<script>
async function refresh(){try{document.getElementById('data').textContent=JSON.stringify(await (await fetch('/status')).json(),null,2)}catch(e){document.getElementById('data').textContent=String(e)}}
async function syncClock(){const r=await fetch('/clock',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'epoch='+Math.floor(Date.now()/1000)});alert(await r.text());refresh()}
refresh();setInterval(refresh,5000);
</script></body></html>
)HTML";
    server.send(200, "text/html", page);
  });
  server.on("/status", HTTP_GET, []() { server.send(200, "application/json", statusJSON()); });
  server.on("/clock", HTTP_POST, []() {
    if (!server.hasArg("epoch")) { server.send(400, "text/plain", "Missing epoch"); return; }
    uint32_t epoch = (uint32_t)strtoul(server.arg("epoch").c_str(), nullptr, 10);
    if (epoch < 1704067200UL || epoch > 4102444800UL) {
      server.send(400, "text/plain", "Invalid epoch"); return;
    }
    struct timeval tv = { (time_t)epoch, 0 };
    settimeofday(&tv, nullptr);
    epochNow();
    server.send(200, "text/plain", "UTC clock synchronized");
  });
  server.on("/log.csv", HTTP_GET, []() {
    if (!sdReady) { server.send(503, "text/plain", "No microSD"); return; }
    if (logFile) { logFile.flush(); logFile.close(); }
    File f = SD.open(LOG_PATH, FILE_READ);
    if (!f) { server.send(404, "text/plain", "No logs yet"); return; }
    server.sendHeader("Content-Disposition", "attachment; filename=taxile.csv");
    server.streamFile(f, "text/csv");
    f.close();
  });
  server.begin();
}

bool connectOBD() {
  if (!sys.link) return false;
  if (obd.init()) {
    obdReady = true;
    Serial.println("OBD connected");
    return true;
  }
  obdReady = false;
  Serial.println("OBD unavailable: retrying");
  return false;
}
void pollOBD() {
  if (!obdReady) return;
  int rpm = -1, speed = -1;
  bool okRPM = obd.readPID(PID_RPM, rpm);
  bool okSpeed = obd.readPID(PID_SPEED, speed);
  uint32_t now = millis();
  lastRPM = okRPM ? rpm : -1;
  lastSpeed = okSpeed ? speed : -1;
  if (!okRPM && !okSpeed) {
    // No accumulation on read failure or reconnection gap.
    previousSpeedValid = false;
    obdReady = false;
    lastReconnect = now;
    Serial.println("OBD read failure; reconnecting");
    return;
  }
  bool engineOn = okRPM && rpm > 400;
  if (engineOn) {
    lastEngineOnAt = now;
    if (!tripActive) beginTrip();
  }
  if (tripActive) {
    double deltaMiles = 0;
    bool validSpeed = okSpeed && speed >= 0 && speed <= MAX_SPEED_KPH;
    if (validSpeed && previousSpeedValid) {
      uint32_t dt = now - lastSpeedAt;
      if (dt > 0 && dt <= MAX_VALID_GAP_MS) {
        double km = (previousKph + speed) * 0.5 * ((double)dt / 3600000.0);
        deltaMiles = km * KM_TO_MILES;
        tripMiles += deltaMiles;
      }
    }
    if (validSpeed) {
      previousKph = speed;
      lastSpeedAt = now;
    }
    previousSpeedValid = validSpeed;
    if (deltaMiles > 0 || millis() - lastFlush >= 15000) {
      appendEvent("SAMPLE", deltaMiles);
      lastFlush = millis();
    }
    if (!engineOn && now - lastEngineOnAt >= TAXILE_IDLE_END_MS) endTrip();
  }
  Serial.printf("RPM=%d speed=%d km/h trip=%.4f mi\n", lastRPM, lastSpeed, tripMiles);
}
void setup() {
  Serial.begin(115200);
  delay(500);
  bootId = esp_random();
  Serial.println("Taxile 0.1");
  SPI.begin();
  sdReady = SD.begin(PIN_SD_CS);
  Serial.println(sdReady ? "SD ready" : "ERROR: no usable microSD");
  openLog();
  setupWiFi();
  configureServer();
  if (sys.begin(true, false)) {
    obd.begin(sys.link);
    connectOBD();
  } else {
    Serial.println("ERROR: Freematics coprocessor unavailable");
  }
  lastReconnect = millis();
  lastSample = millis();
  lastNtpAttempt = millis() - 30000;
}
void loop() {
  server.handleClient();
  clockUpdate();
  uint32_t now = millis();
  if (!obdReady && now - lastReconnect >= RECONNECT_MS) {
    lastReconnect = now;
    connectOBD();
  }
  if (now - lastSample >= TAXILE_SAMPLE_MS) {
    lastSample = now;
    pollOBD();
  }
  // If connection is lost midway through a trip, close it after inactivity;
  // no mileage is fabricated during the outage.
  if (tripActive && millis() - lastEngineOnAt >= TAXILE_IDLE_END_MS) endTrip();
  delay(10);
}
