#pragma once
#include <SD.h>
#include <ArduinoJson.h>
#include <freertos/semphr.h>
#include <atomic>

// All SD calls, including directory enumeration, run under this lock.
// Files become immutable before upload. No acknowledged state is stored in RAM.
class Outbox {
  SemaphoreHandle_t lock = nullptr;
  String active;
  String boot;
  uint32_t part = 0;
  size_t count = 0;
  bool sealLocked() {
    if (active.isEmpty()) return true;
    String dest = active.substring(0, active.length() - 5) + ".ndjson";
    if (!SD.rename(active, dest)) return false;
    active = ""; count = 0; return true;
  }
 public:
  std::atomic<bool> ready{false};
  String error;
  uint32_t damaged = 0;
  String statusError() {
    if (!lock) return error;
    xSemaphoreTake(lock, portMAX_DELAY);
    String s = error; xSemaphoreGive(lock); return s;
  }
  void begin(const String& bootId) {
    boot = bootId;
    lock = xSemaphoreCreateMutex();
    if (!lock || !SD.begin(PIN_SD_CS, SPI, 4000000)) {
      error = "No FAT32 microSD; mileage cannot be saved"; return;
    }
    if (!SD.exists("/outbox") && !SD.mkdir("/outbox")) {
      error = "Cannot create outbox"; return;
    }
    // Interrupted writes: leave original .open untouched until a recovered copy
    // is fully written, then rename it. A reboot at any boundary is repeatable.
    File dir = SD.open("/outbox");
    String paths[32]; size_t n = 0;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String path = f.path(); f.close();
      if (path.endsWith(".open") && n < 32) paths[n++] = path;
    }
    dir.close();
    for (size_t i = 0; i < n; ++i) {
      String dest = paths[i].substring(0, paths[i].length()-5) + ".ndjson";
      String tmp = paths[i] + ".recover";
      if (SD.exists(dest)) { SD.remove(paths[i]); continue; }
      SD.remove(tmp);
      File in = SD.open(paths[i], FILE_READ), out = SD.open(tmp, FILE_WRITE);
      if (!in || !out) { error = "Cannot recover interrupted log"; return; }
      bool good = true;
      while (in.available()) {
        String line; bool newline = false;
        while (in.available()) {
          char c = in.read(); if (c == '\n') { newline = true; break; }
          line += c; if (line.length() > 1536) break;
        }
        StaticJsonDocument<1536> d;
        if (!newline || deserializeJson(d, line) || !d["event_id"].is<const char*>()) {
          ++damaged; break; // preserve valid prefix, report missing tail
        }
        line += '\n';
        if (out.print(line) != line.length()) { good = false; break; }
      }
      in.close(); out.flush(); out.close();
      if (!good || !SD.rename(tmp, dest)) { error = "Recovery write failed"; return; }
      SD.remove(paths[i]);
    }
    if (n == 32) { error = "Too many interrupted files; repair SD on PC"; return; }
    ready = true;
  }
  bool append(const String& json) {
    if (!ready) return false;
    xSemaphoreTake(lock, portMAX_DELAY);
    bool ok = true;
    if (active.isEmpty()) {
      char suffix[16]; snprintf(suffix, sizeof(suffix), "-%08lu.open", (unsigned long)++part);
      active = "/outbox/" + boot + suffix;
    }
    File f = SD.open(active, FILE_APPEND);
    String line = json + "\n";
    ok = f && f.print(line) == line.length();
    if (f) { f.flush(); f.close(); }
    if (ok && ++count >= 60) ok = sealLocked();
    if (!ok) { ready = false; error = "SD write failed; recording stopped. Check card."; }
    xSemaphoreGive(lock);
    return ok;
  }
  bool seal() {
    if (!ready) return false;
    xSemaphoreTake(lock, portMAX_DELAY);
    bool ok = sealLocked();
    if (!ok) { ready = false; error = "Cannot finalize upload file"; }
    xSemaphoreGive(lock); return ok;
  }
  bool next(String& name, String& body) {
    if (!ready) return false;
    xSemaphoreTake(lock, portMAX_DELAY);
    File dir = SD.open("/outbox"); name = "";
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String path = f.path(); f.close();
      if (path.endsWith(".ndjson") && (name.isEmpty() || path < name)) name = path;
    }
    dir.close(); body = "";
    if (!name.isEmpty()) {
      File f = SD.open(name);
      if (!f || f.size() > 96000) { error = "Invalid queued file; inspect microSD"; name = ""; }
      else { body.reserve(f.size()+1); while (f.available()) body += char(f.read()); }
      f.close();
    }
    xSemaphoreGive(lock); return !name.isEmpty();
  }
  bool acknowledge(const String& name) {
    xSemaphoreTake(lock, portMAX_DELAY);
    bool ok = SD.remove(name);
    xSemaphoreGive(lock); return ok;
  }
};
