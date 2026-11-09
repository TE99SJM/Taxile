#pragma once
#include <stdint.h>

// Platform-independent integration. Never bridge a missing or overlong sample.
class Mileage {
 public:
  double total = 0;
  uint64_t missedMs = 0;
  uint64_t lastAt = 0;
  double lastKph = 0;
  bool previousValid = false;
  bool hadSample = false;
  double scale = 1.0;
  static constexpr uint32_t maxGapMs = 5000;
  void reset(double calibration = 1) {
    total = 0; missedMs = 0; lastAt = 0; lastKph = 0;
    previousValid = false; hadSample = false; scale = calibration;
  }
  double sample(uint64_t at, int kph, bool valid) {
    valid = valid && kph >= 0 && kph <= 255;
    double delta = 0;
    if (hadSample && at > lastAt) {
      uint64_t dt = at - lastAt;
      if (valid && previousValid && dt <= maxGapMs)
        delta = (lastKph + kph) * 0.5 * dt / 3600000.0 * 0.621371192237334 * scale;
      else missedMs += dt;
    }
    lastAt = at; lastKph = kph; previousValid = valid; hadSample = true;
    total += delta;
    return delta;
  }
};
