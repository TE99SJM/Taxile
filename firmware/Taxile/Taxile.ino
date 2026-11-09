/* Taxile 0.4.0 - Freematics ONE+ ESP32. See LICENSE and THIRD_PARTY.md. */
#include <Arduino.h>
#include <FreematicsPlus.h>
#include <SPI.h>
#include <SD.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_timer.h>
#include <esp_sleep.h>
#include <mbedtls/sha256.h>
#include <atomic>
#include <time.h>
#include "Mileage.h"
#include "Settings.h"
#include "Queue.h"
#include "WebPage.h"
#include "Diagnostics.h"
#include "Vehicle.h"

static constexpr uint32_t SAMPLE_MS = 1000, END_MS = 120000;
static constexpr uint32_t WIFI_WINDOW_MS = 180000, WIFI_RETRY_MS = 900000;
static constexpr uint32_t AP_WINDOW_MS = 600000;
FreematicsESP32 sys;
COBD obd;
MEMS_I2C* motionSensor = nullptr;
WebServer web(80);
Settings cfg;
Outbox queue;
Mileage mileage;
VehicleIdentity vehicle;
uint64_t nextVIN=0;
String deviceId, bootId;
SemaphoreHandle_t stateLock;
SemaphoreHandle_t sleepGate;
struct GateGuard {
 bool held=true;
 GateGuard() { xSemaphoreTake(sleepGate,portMAX_DELAY); }
 void release() { if(held) { xSemaphoreGive(sleepGate); held=false; } }
 ~GateGuard() { release(); }
};
std::atomic<bool> active(false), parked(false), networkBusy(false), configPause(false);
std::atomic<bool> storageOK(false);
std::atomic<bool> clockChanged(false);
struct Snapshot { int rpm=-1, speed=-1; float volts=0; double miles=0; uint64_t missing=0;
  bool obd=false, motion=false; uint32_t trip=0; String vin, tripVIN; } state;
bool chipReady=false, obdReady=false, apOn=false, wifiOn=false;
uint32_t eventSequence=0, trip=0;
uint64_t lastRunning=0, lastConnect=0, lastSample=0, lastVoltage=0;
uint64_t wifiUntil=0, nextWifi=0, apUntil=0, nextUpload=0;
uint64_t retryMs=5000, lastClockEpoch=0, lastClockAt=0;
// Main-task writes hold sleepGate; acquisition reads while holding that gate.
uint64_t diagnosticUntil=0;
String syncStatus="Not configured", csrf;

uint64_t uptimeMs() { return esp_timer_get_time()/1000ULL; }
uint64_t utcNow() { time_t t=time(nullptr); return t>=1704067200 && t<4102444800LL ? t : 0; }
String randomId() { char b[33]; snprintf(b,sizeof(b),"%08lx%08lx%08lx%08lx",
 (unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random()); return b; }
Snapshot snapshot() { xSemaphoreTake(stateLock,portMAX_DELAY); Snapshot s=state; xSemaphoreGive(stateLock); return s; }
void publish(int rpm,int speed,float volts) {
 xSemaphoreTake(stateLock,portMAX_DELAY);
 state.rpm=rpm; state.speed=speed; state.volts=volts; state.miles=mileage.total;
 state.missing=mileage.missedMs; state.obd=obdReady; state.motion=motionSensor!=nullptr; state.trip=trip; state.vin=vehicle.current; state.tripVIN=vehicle.recordedVIN();
 xSemaphoreGive(stateLock);
}
// Only the acquisition task emits events, so sequence and SD order agree.
void emitEvent(const char* type,double delta=0,int speed=-1,int rpm=-1,uint32_t interval=0,uint64_t measuredAt=0) {
 StaticJsonDocument<1536> d;
 d["schema"]=2; d["device_id"]=deviceId; d["boot_id"]=bootId;
 d["seq"]=++eventSequence; d["event_id"]=bootId+"-"+String(eventSequence);
 bool tripEvent=!strcmp(type,"START") || !strcmp(type,"SAMPLE") || !strcmp(type,"END");
 const char* vin=tripEvent?vehicle.recordedVIN():vehicle.current;
 d["vin"]=vin; d["vehicle_id"]=strlen(vin)?String(vin):"unknown-"+bootId+"-t"+String(trip);
 d["vehicle_identification"]=strlen(vin)?"vin":"unknown";
 d["trip_id"]=trip ? bootId+"-t"+String(trip) : "";
 uint64_t now=uptimeMs(); if(!measuredAt) measuredAt=now;
 d["type"]=type; d["uptime_ms"]=measuredAt;
 uint64_t epoch=utcNow(); if(epoch) d["epoch_utc"]=epoch-(now-measuredAt)/1000; else d["epoch_utc"]=nullptr;
 d["speed_kph"]=speed; d["rpm"]=rpm; d["delta_miles"]=delta;
 d["trip_miles"]=mileage.total; d["missing_ms"]=mileage.missedMs;
 d["interval_ms"]=interval; d["calibration"]=cfg.calibration;
 String json; serializeJson(d,json); storageOK=queue.append(json);
}
void initMotion() {
 motionSensor=new ICM_42627;
 if(motionSensor->begin()) return; delete motionSensor;
 motionSensor=new ICM_20948_I2C;
 if(motionSensor->begin()) return; delete motionSensor;
 motionSensor=new MPU9250;
 if(motionSensor->begin()) return; delete motionSensor; motionSensor=nullptr;
}
void identifyVehicle() {
 vehicle.resetConnection();
 char response[512]={0};
 int received=obd.link->sendCommand("0902\r",response,sizeof(response)-1,OBD_TIMEOUT_LONG);
 if(received>0 && received<(int)sizeof(response)-2) vehicle.identify(response);
 nextVIN=uptimeMs()+30000;
 // Do not put VINs in serial logs or public build output.
 Serial.println(strlen(vehicle.current)?"Vehicle VIN identified":"Vehicle unknown: VIN unavailable; mileage stays separate");
}
bool connectOBD() {
 vehicle.resetConnection();
 if(!chipReady) return false;
 obdReady=obd.init();
 if(obdReady) identifyVehicle();
 return obdReady;
}
void acquisition(void*) {
 float volts=0, baseline[3]={0,0,0}; bool baselineValid=false;
 uint32_t motionHits=0; uint64_t parkAt=0;
 emitEvent("BOOT");
 for(;;) {
  GateGuard guard;
  uint64_t now=uptimeMs();
  if(configPause) { guard.release(); vTaskDelay(pdMS_TO_TICKS(20)); continue; }
  uint64_t epoch=utcNow();
  // A CLOCK anchor lets the receiver date earlier events from this same boot.
  if(epoch && (!lastClockEpoch || clockChanged.exchange(false) || now-lastClockAt>=3600000)) {
    emitEvent("CLOCK"); lastClockEpoch=epoch; lastClockAt=now;
    if(parked) queue.seal();
  }
  if(parked) {
    bool wake=false;
    if(motionSensor) {
      float a[3];
      if(motionSensor->read(a)) {
        if(!baselineValid) { for(int i=0;i<3;++i) baseline[i]=a[i]; baselineValid=true; }
        float squared=0;
        for(int i=0;i<3;++i) { float diff=a[i]-baseline[i]; squared+=diff*diff; }
        // Freematics accelerometers report g; require repeated movement.
        if(squared>0.04f) ++motionHits; else motionHits=0;
        if(motionHits>=3) wake=true;
      }
    }
    // Adapter voltage reads do not request vehicle PIDs. Never repeatedly
    // initialize the ECU just to check whether a parked engine has started.
    if(chipReady && now-lastVoltage>=10000) {
      lastVoltage=now; volts=obd.getVoltage();
      if(volts>=13.2f && volts<=16.0f) wake=true;
    }
    if(wake && now-parkAt>=5000) {
      parked=false; baselineValid=false; motionHits=0; lastRunning=now;
      sys.reactivateLink(); obdReady=false; lastConnect=0;
      Serial.println("Wake: motion/charging voltage");
    }
    publish(-1,-1,volts); guard.release(); vTaskDelay(pdMS_TO_TICKS(200)); continue;
  }
  if(!obdReady && (!lastConnect || now-lastConnect>=10000)) { lastConnect=now; connectOBD(); }
  if(obdReady && !active && !strlen(vehicle.current) && now>=nextVIN) identifyVehicle();
  if(now-lastSample>=SAMPLE_MS && obdReady) {
    lastSample=now;
    int speed=-1,rpm=-1;
    bool speedOK=obd.readPID(PID_SPEED,speed);
    // Timestamp speed immediately, before the potentially slow RPM request.
    uint64_t speedAt=uptimeMs();
    bool rpmOK=obd.readPID(PID_RPM,rpm);
    bool running=(rpmOK && rpm>300) || (speedOK && speed>0);
    if(running) {
      lastRunning=uptimeMs();
      if(!active) { active=true; ++trip; vehicle.startTrip(); mileage.reset(cfg.calibration); emitEvent("START",0,speed,rpm); }
    }
    if(active) {
      uint64_t previous=mileage.lastAt;
      bool had=mileage.hadSample;
      double delta=mileage.sample(speedAt,speed,speedOK);
      uint64_t dt=had ? speedAt-previous : 0;
      emitEvent("SAMPLE",delta,speedOK?speed:-1,rpmOK?rpm:-1,dt>UINT32_MAX?UINT32_MAX:dt,speedAt);
    }
    if(!speedOK && !rpmOK) {
      // A new OBD connection is a new identity boundary. Never integrate
      // across unplug/replug or carry a previous vehicle into the next trip.
      if(active) { emitEvent("END"); active=false; queue.seal(); }
      obdReady=false; vehicle.resetConnection();
    }
    if(uptimeMs()-lastVoltage>=30000) { lastVoltage=uptimeMs(); volts=obd.getVoltage(); }
    publish(rpmOK?rpm:-1,speedOK?speed:-1,volts);
  }
  if(uptimeMs()-lastRunning>=END_MS && uptimeMs()>=diagnosticUntil) {
    if(active) {
      // Count the unobserved tail as missing time; never add invented miles.
      mileage.sample(uptimeMs(),-1,false); emitEvent("END"); active=false;
    }
    queue.seal();
    if(chipReady) sys.resetLink();
    obdReady=false; vehicle.resetConnection(); parked=true; parkAt=uptimeMs(); baselineValid=false;
    publish(-1,-1,volts); Serial.println("Parked: waiting for motion or charging voltage");
  }
  guard.release(); vTaskDelay(pdMS_TO_TICKS(10));
 }
}
bool authenticated(bool write=false) {
 if(!web.authenticate("admin",cfg.admin.c_str())) { web.requestAuthentication(DIGEST_AUTH); return false; }
 if(write && web.header("X-Taxile-CSRF")!=csrf) { web.send(403,"text/plain","Reload the page"); return false; }
 return true;
}
// Serialize every diagnostic transaction against acquisition and sleep.
void diagnostics(bool clear) {
 if(!authenticated(true)) return;
 if(clear && web.arg("plain")!="CLEAR") { web.send(400,"text/plain","Explicit CLEAR confirmation required"); return; }
 if(xSemaphoreTake(sleepGate,pdMS_TO_TICKS(3000))!=pdTRUE) { web.send(503,"text/plain","Vehicle busy; retry"); return; }
 diagnosticUntil=uptimeMs()+120000;
 bool wasParked=parked.exchange(false);
 if(wasParked && chipReady) { sys.reactivateLink(); obdReady=false; }
 if(!obdReady) connectOBD();
 int rpm=-1,speed=-1;
 bool stationary=obdReady && obd.readPID(PID_RPM,rpm) && obd.readPID(PID_SPEED,speed) && rpm==0 && speed==0;
 if(!stationary) { xSemaphoreGive(sleepGate); web.send(409,"text/plain","Ignition ON, engine OFF, vehicle stationary required; could not verify RPM/speed"); return; }
 StaticJsonDocument<4096> d; char response[1024]={0};
 char protocolReply[64]={0};
 obd.link->sendCommand("ATDPN\r",protocolReply,sizeof(protocolReply)-1,OBD_TIMEOUT_SHORT);
 int protocol=diagnosticProtocol(protocolReply);
 if(protocol<0) { xSemaphoreGive(sleepGate); web.send(502,"text/plain","Could not identify OBD protocol; scan not sent"); return; }
 const char* command=clear?"04\r":"03\r";
 int received=obd.link->sendCommand(command,response,sizeof(response)-1,OBD_TIMEOUT_LONG);
 response[sizeof(response)-1]=0;
 // Never report a timeout or NO DATA as an empty successful scan.
 bool ok=received>0 && received<(int)sizeof(response)-2 && parseDiagnostic(response,clear,d,protocol>=6);
 if(clear) d.remove("codes");
 d["vin"]=vehicle.current; d["device"]=deviceId; d["ok"]=ok; d["kind"]=clear?"clear_acknowledgement":"stored";
 d["scope"]="Generic OBD-II emissions codes; not ABS/airbag/body modules";
 if(!ok) d["error"]="No valid ECU acknowledgement; result unknown. Retry with ignition ON.";
 if(clear && ok) d["message"]="ECU acknowledged clear. Read codes again; permanent codes may remain.";
 String out; serializeJson(d,out);
 xSemaphoreGive(sleepGate);
 web.sendHeader("Cache-Control","no-store"); web.send(ok?200:502,"application/json",out);
}
void setupWeb() {
 const char* headers[]={"X-Taxile-CSRF"}; web.collectHeaders(headers,1);
 web.on("/",HTTP_GET,[](){ if(!authenticated()) return;
   web.sendHeader("Cache-Control","no-store"); web.send_P(200,"text/html",TAXILE_PAGE); });
 web.on("/api/status",HTTP_GET,[](){ if(!authenticated()) return;
   Snapshot s=snapshot(); StaticJsonDocument<2048> d;
   d["version"]="0.4.0"; d["vin"]=s.vin; d["trip_vin"]=s.tripVIN;
   d["vehicle_identification"]=s.vin.isEmpty()?"unknown":"vin"; d["device"]=deviceId; d["active"]=active.load(); d["parked"]=parked.load();
   d["obd"]=s.obd; d["storage"]=storageOK.load(); d["storage_error"]=queue.statusError();
   d["recovered_partial_files"]=queue.damaged; d["motion_sensor"]=s.motion;
   d["speed_kph"]=s.speed; d["rpm"]=s.rpm; d["volts"]=s.volts;
   d["trip_miles"]=s.miles; d["missing_seconds"]=s.missing/1000.0;
   d["utc_epoch"]=utcNow(); d["sync"]=syncStatus; d["ip"]=WiFi.localIP().toString();
   d["ssid"]=cfg.ssid; d["endpoint"]=cfg.endpoint; d["allow_http"]=cfg.allowHttp;
   d["calibration"]=cfg.calibration; d["csrf"]=csrf;
   String out; serializeJson(d,out); web.sendHeader("Cache-Control","no-store"); web.send(200,"application/json",out);
 });
 web.on("/api/clock",HTTP_POST,[](){ if(!authenticated(true)) return;
   if(active) { web.send(409,"text/plain","Park first"); return; }
   StaticJsonDocument<128> d;
   if(deserializeJson(d,web.arg("plain")) || !d["epoch"].is<uint64_t>()) { web.send(400,"text/plain","Invalid clock"); return; }
   uint64_t epoch=d["epoch"];
   if(epoch<1704067200 || epoch>=4102444800ULL) { web.send(400,"text/plain","Invalid clock"); return; }
   timeval tv={(time_t)epoch,0}; settimeofday(&tv,nullptr); clockChanged=true; web.send(200,"text/plain","Clock set");
 });
 web.on("/api/config",HTTP_POST,[](){ if(!authenticated(true)) return;
   if(active || !parked) { web.send(409,"text/plain","Wait until the logger shows parked"); return; }
   if(web.arg("plain").length()>7000) { web.send(413,"text/plain","Settings too large"); return; }
   DynamicJsonDocument d(8192);
   if(deserializeJson(d,web.arg("plain"))) { web.send(400,"text/plain","Invalid JSON"); return; }
   String ssid=d["ssid"]|"", pass=d["password"]|"", endpoint=d["endpoint"]|"";
   String token=d["token"]|"", ca=d["ca"]|"";
   bool http=d["allow_http"]|false; double scale=d["calibration"]|1.0;
   if(pass.isEmpty()) pass=cfg.password; if(token.isEmpty()) token=cfg.token; if(ca.isEmpty()) ca=cfg.ca;
   if(ssid.length()>32 || pass.length()>63 || token.length()>512 || endpoint.length()>512 ||
      scale<0.5 || scale>1.5 || !isfinite(scale) ||
      (!endpoint.isEmpty() && !(endpoint.startsWith("https://") || (http && endpoint.startsWith("http://")))) ||
      endpoint.indexOf('@')>=0 || endpoint.indexOf('\n')>=0 || token.indexOf('\r')>=0 || token.indexOf('\n')>=0 ||
      (endpoint.startsWith("https://") && ca.indexOf("BEGIN CERTIFICATE")<0) ||
      (!endpoint.isEmpty() && token.length()<32)) {
     web.send(400,"text/plain","Check Wi-Fi, URL, token (32+ characters), CA certificate and calibration (0.5–1.5)"); return;
   }
   // Serialize only accepted fields. One NVS blob prevents half-saved settings.
   d.clear(); d["ssid"]=ssid; d["password"]=pass; d["endpoint"]=endpoint; d["token"]=token;
   d["ca"]=ca; d["allow_http"]=http; d["calibration"]=scale;
   String json; serializeJson(d,json);
   configPause=true;
   xSemaphoreTake(sleepGate,portMAX_DELAY);
   if(active) { xSemaphoreGive(sleepGate); configPause=false; web.send(409,"text/plain","Vehicle started; settings not saved"); return; }
   queue.seal();
   if(!cfg.save(json)) { xSemaphoreGive(sleepGate); configPause=false; web.send(500,"text/plain","Settings were not saved"); return; }
   web.send(200,"text/plain","Saved. Restarting; reconnect in about 20 seconds."); delay(500); ESP.restart();
 });
 web.on("/api/diagnostics/read",HTTP_POST,[](){ diagnostics(false); });
 web.on("/api/diagnostics/clear",HTTP_POST,[](){ diagnostics(true); });
 web.begin();
}
void startWifi(bool withAP=false) {
 WiFi.mode(withAP?WIFI_AP_STA:WIFI_STA); wifiOn=true;
 if(withAP) { WiFi.softAP(("Taxile-"+deviceId.substring(deviceId.length()-6)).c_str(),cfg.admin.c_str()); apOn=true; apUntil=uptimeMs()+AP_WINDOW_MS; }
 if(!cfg.ssid.isEmpty()) WiFi.begin(cfg.ssid.c_str(),cfg.password.c_str());
 wifiUntil=uptimeMs()+WIFI_WINDOW_MS;
 configTime(0,0,"pool.ntp.org","time.google.com");
}
void uploadOne() {
 if(cfg.endpoint.isEmpty() || cfg.token.isEmpty() || WiFi.status()!=WL_CONNECTED || active || uptimeMs()<nextUpload) return;
 String name,body;
 if(!queue.next(name,body)) { syncStatus="Queue empty"; nextUpload=uptimeMs()+5000; return; }
 if(body.isEmpty()) { queue.acknowledge(name); return; }
 String batch=name.substring(name.lastIndexOf('/')+1);
 unsigned char hash[32]; char hex[65];
 mbedtls_sha256_ret((const unsigned char*)body.c_str(),body.length(),hash,0);
 for(int i=0;i<32;++i) snprintf(hex+i*2,3,"%02x",hash[i]);
 WiFiClient plain; WiFiClientSecure tls; HTTPClient http;
 bool secure=cfg.endpoint.startsWith("https://");
 if(secure && (!utcNow() || cfg.ca.isEmpty())) { syncStatus="HTTPS needs valid time and a CA certificate"; nextUpload=uptimeMs()+30000; return; }
 if(!secure && !cfg.allowHttp) { syncStatus="HTTP disabled"; return; }
 if(secure) { tls.setCACert(cfg.ca.c_str()); tls.setHandshakeTimeout(8); }
 http.setConnectTimeout(5000); http.setTimeout(8000); http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
 bool begun=secure?http.begin(tls,cfg.endpoint):http.begin(plain,cfg.endpoint);
 if(!begun) { syncStatus="Invalid receiver URL"; nextUpload=uptimeMs()+60000; return; }
 http.addHeader("Authorization","Bearer "+cfg.token);
 http.addHeader("Content-Type","application/x-ndjson");
 http.addHeader("X-Taxile-Batch",batch); http.addHeader("X-Taxile-Device",deviceId);
 networkBusy=true;
 int code=http.POST((uint8_t*)body.c_str(),body.length());
 bool accepted=false;
 if(code==200 && http.getSize()>0 && http.getSize()<1024) {
   StaticJsonDocument<1024> d;
   accepted=!deserializeJson(d,http.getString()) && d["ok"]==true && d["batch_id"].as<String>()==batch && d["sha256"].as<String>()==hex;
 }
 http.end(); networkBusy=false;
 if(accepted && queue.acknowledge(name)) {
   syncStatus="Uploaded "+batch; retryMs=5000; nextUpload=uptimeMs()+200;
 } else {
   syncStatus="Retry pending (HTTP "+String(code)+")";
   nextUpload=uptimeMs()+retryMs+(esp_random()%2000); retryMs=min(retryMs*2,(uint64_t)300000);
 }
}
void setup() {
 Serial.begin(115200); delay(300); Serial.println("\nTaxile 0.4.0");
 stateLock=xSemaphoreCreateMutex();
 sleepGate=xSemaphoreCreateMutex();
 if(!stateLock || !sleepGate || !cfg.load()) { Serial.println("FATAL: settings storage unavailable"); for(;;) delay(1000); }
 char id[20]; snprintf(id,sizeof(id),"%012llx",ESP.getEfuseMac()); deviceId=id;
 bootId=randomId(); csrf=randomId();
 Serial.printf("Device: %s\nSetup user: admin\nSetup password: %s\n",deviceId.c_str(),cfg.admin.c_str());
 Serial.println("Hotspot enabled for 10 minutes. Open http://192.168.4.1 . Type SETUP to reopen it.");
 chipReady=sys.begin(true,false);
 if(chipReady) { obd.begin(sys.link); sys.gpsEnd(); }
 pinMode(PIN_GPS_POWER,OUTPUT); digitalWrite(PIN_GPS_POWER,LOW);
 SPI.begin(); queue.begin(bootId); storageOK=queue.ready.load();
 initMotion(); lastRunning=uptimeMs();
 startWifi(true); setupWeb();
 if(xTaskCreatePinnedToCore(acquisition,"vehicle",12288,nullptr,2,nullptr,1)!=pdPASS) {
   Serial.println("FATAL: acquisition task failed"); for(;;) delay(1000);
 }
}
void loop() {
 static bool wasParked=false; static String command;
 uint64_t now=uptimeMs();
 if(Serial.available()) {
   char c=Serial.read();
   if(c=='\n') { command.trim(); if(command=="SETUP" && !active) startWifi(true); command=""; }
   else if(command.length()<32) command+=c;
 }
 bool isParked=parked.load();
 if(isParked && !wasParked) { if(!wifiOn) startWifi(); wifiUntil=now+WIFI_WINDOW_MS; nextUpload=0; }
 wasParked=isParked;
 if(apOn && now>=apUntil && now>=diagnosticUntil) { WiFi.softAPdisconnect(true); apOn=false; }
 // Stop radio when driving after initial setup, or once the parked sync window ends.
 if(wifiOn && !apOn && now>=diagnosticUntil && ((active.load()) || (isParked && now>=wifiUntil))) {
   WiFi.disconnect(true); WiFi.mode(WIFI_OFF); wifiOn=false; nextWifi=now+WIFI_RETRY_MS;
 }
 if(!wifiOn && isParked && now>=nextWifi && !cfg.ssid.isEmpty()) startWifi();
 if(wifiOn) { web.handleClient(); uploadOne(); }
 if(!wifiOn && parked && xSemaphoreTake(sleepGate,0)==pdTRUE) {
   if(parked) { esp_sleep_enable_timer_wakeup(200000); esp_light_sleep_start(); }
   xSemaphoreGive(sleepGate);
 }
 delay(10);
}
