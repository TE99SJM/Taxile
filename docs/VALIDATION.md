# 0.4.0 diagnostic validation

Passed: 21 Python tests (desktop transport/security/error handling plus inherited receiver/report tests); production C++ parser tests (P/C/B/U formatting, CAN count byte, legacy replies, multiline replies, multiple ECUs, deduplication, empty positive responses, timeout/error/truncation rejection); inherited native mileage tests.

Compiled successfully: original ESP32 UART-link target, PlatformIO espressif32 6.9.0 / Arduino ESP32 2.0.17. Firmware flash usage 1,055,853 bytes, static RAM 48,324 bytes.

Native vehicle tests passed: CAN/legacy VIN parsing, malformed/incomplete/mismatching VIN rejection, known-to-known swaps, known-to-unknown swaps and frozen unknown trip identity. Server tests cover multiple vehicles on one dongle, same VIN across boots, historical untagged logs, invalid identities, CSV exports and transactional rejection of an identity change inside a trip.

Not completed: actual VIN lookup and two-vehicle swaps, Windows EXE build, visual Windows GUI inspection, physical read/clear on ONE+, CAN protocol identification response, radio windows and battery draw. Compiled ESP32 images are included. Verify hardware, backup flash, compile, flash, read first, save report, then explicitly clear only when intended.

## Inherited validation notes

# Validation record — Taxile 0.2.0

Validated in the development environment on 2026-11-08 America/Chicago
(2026-11-09 UTC). No physical Freematics unit or vehicle was available here.

## Completed software checks

- PlatformIO ESP32 firmware compiled and linked successfully using the pinned
  toolchain and actual official Freematics library (with documented class rename).
  Firmware size: 1,049,221 bytes of a 1,966,080-byte app partition; static RAM:
  48,244 bytes of 327,680. Runtime heap/stack still require device measurement.
- Nine Python unit/integration tests passed: existing legacy report test;
  identical retry after database reopen; batch/event conflict rejection; event
  deduplication across batches; atomic rejection of malformed/truncated uploads;
  same-boot timestamp recovery; no fabricated dates across boots; midnight
  allocation; real localhost HTTP authentication, upload and CSV response.
- Native C++ test uses the firmware's actual Mileage class: steady speed,
  trapezoidal acceleration, missing readings, long gaps, impossible speeds,
  calibration and timestamps beyond 32-bit millis rollover.
- Python source and embedded browser JavaScript syntax checks passed.
- Git whitespace/error check passed.

Docker execution, physical SD power-cut behavior, HTTPS certificate exchange on
ESP32, hotspot behavior, motion sensor operation, in-car sampling and current
draw were not tested in this environment. Receiver tests used its real HTTP
server and SQLite implementation locally, not a deployed home service.

## Required bench and vehicle acceptance

1. Confirm original ESP32 chip and UART-coprocessor ONE+ revision; preserve original
   flash. Confirm the binary is the correct architecture before flashing.
2. Verify setup hotspot, digest sign-in, runtime settings save, NTP/phone time,
   valid SD and OBD readings. Confirm incorrect password/token fails.
3. With engine idling and speed zero, trip mileage must stay zero. Turn ignition
   off; verify trip closes after two minutes and upload occurs at home.
4. Drive a known route and compare beginning/ending dash odometer with the
   receiver's estimated total. Tune calibration only from repeated measurements.
   Verify automatic wake before moving and that no opening mileage is missed.
5. Repeat out of Wi-Fi range, return home, and verify all events arrive once.
   Stop the receiver during upload; restart and check that retries do not double
   daily/trip totals. A different acknowledgment/hash must leave the batch queued.
6. On a test card, interrupt power while recording and while finalizing a batch.
   Check valid-prefix recovery, incomplete-trip indication and total integrity.
   Test missing/full card and ensure the device visibly reports recording failure.
7. Observe parked behavior and measure current at the vehicle supply, including
   periodic Wi-Fi windows. Verify the vehicle's modules sleep normally and no
   nuisance wakeups occur. Test after overnight parking and restart. Validate
   charging-voltage and motion thresholds for this actual vehicle/unit.
8. Confirm no-time/full-power-loss records remain undated rather than being
   assigned the upload date. Verify same-boot home sync correctly dates the trip.

Acceptance is not complete until these hardware checks pass. Software tests are
not a substitute for these measurements.
