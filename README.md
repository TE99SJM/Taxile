# Taxile 0.4.0 — mileage logger + PC diagnostics

This version extends the 0.2.0 package with a Windows desktop app, authenticated firmware endpoints for reading stored generic OBD-II trouble codes and clearing them, plus native parser and desktop transport tests. Start with [desktop/README.md](desktop/README.md).

**Build status:** ESP32 firmware compilation passed (1,055,853 bytes flash, 48,324 bytes static RAM). Compiled images are included under `prebuilt/`. All 21 Python tests and native diagnostics/mileage tests passed. Windows launcher/source and an EXE build script are included; no compiled Windows EXE is included. Device and Windows UI testing remain outstanding. Confirm the hardware target and make a full flash backup before flashing.

## Automatic vehicle identification

The ONE+ requests the vehicle VIN with standard OBD-II Mode 09 PID 02 at each connection. Normal unplug/replug into another vehicle starts a fresh boot and fresh VIN lookup. Every new trip freezes the current identity, and each mileage event carries `vehicle_id`, `vin` and `vehicle_identification`. It never persists a last-vehicle VIN into the next connection.

Daily reports, trip reports and CSV exports separate vehicles by VIN, even when the same dongle is moved between them. `/v1/summary` also contains per-vehicle totals. VIN is shown in the setup webpage and PC status view. The same VIN stays the same vehicle across reboots; no make/model lookup or internet service is required.

If the ECU does not return a complete valid VIN, recording continues under a distinct **unknown** trip identity. Unknown history and older untagged logs are never assigned to a later detected vehicle. VIN lookup retries while waiting for a trip; a trip that starts unknown remains unknown. An OBD communication loss closes the current trip before reconnecting. Unplugged/power-loss trips may remain incomplete; their saved samples still belong to their original vehicle.

Update the receiving server along with the firmware: schema 2 adds vehicle identity, while the new server still accepts schema 1 historical data. Back up your database before deployment. Generic VIN support and physical swap behavior must be checked on each vehicle; automatic identification cannot be guaranteed on a vehicle that does not expose its VIN through OBD-II. Calibration remains device-wide, so confirm distance accuracy separately on each vehicle.

## New diagnostics API

- `POST /api/diagnostics/read`: read stored Mode 03 codes.
- `POST /api/diagnostics/clear`: clear Mode 04, body must be literal `CLEAR`.
- Both require Digest `admin` authentication and `X-Taxile-CSRF` from authenticated `/api/status`.
- Both acquire the vehicle mutex, wake the link if parked, verify zero RPM/speed and extend the diagnostic awake window. A negative result or missing ECU acknowledgement returns an error.
- Existing mileage recording and receiving service remain included. Mileage integration flags prolonged sample gaps rather than inventing distance during diagnostic transactions.

The sections below describe the inherited mileage functions.

Firmware and a receiving service for a **Freematics ONE+ with the original ESP32**.
Built for the existing 2018 Ram 1500 project, with a configurable destination.
The software records trips while offline, stores them on microSD, and uploads
when it connects to home Wi-Fi after parking.

**Hardware validation is still required.** A successful build and software tests
cannot prove your hardware revision, wake behavior, parked battery draw or vehicle
PID accuracy. Do not flash an ESP32-C3 or original AVR Freematics ONE with this build.
The included upstream driver uses the UART coprocessor link; older SPI-only
hardware needs a different driver configuration. Identify the unit first.

## Included

- Automatic trip detection using read-only standard OBD speed and engine RPM.
- One-second target speed sampling on a separate acquisition task. Network
  requests do not run in the vehicle acquisition task. OBD timeouts and SD writes
  can still delay samples; intervals over five seconds are excluded and flagged.
- Speed integration with a calibration factor; this is **estimated mileage, not
  a reading of the dashboard odometer**. No manufacturer-specific Ram odometer PID
  is assumed. GPS and location tracking are not required or implemented here.
- FAT32 microSD outbox. Every event is flushed. Up to 60 events form an immutable
  upload batch. Interrupted `.open` files recover their valid prefix on reboot.
- Retry with backoff, stable event IDs, SHA-256 acknowledgment verification and
  transactional receiver deduplication. A successful upload is deleted from the
  outbox only after the receiver commits it. Unsent records are never rotated out.
- Engine-off grace period of two minutes, then a three-minute home Wi-Fi window.
  Failed uploads retry in a new window every 15 minutes while parked. The initial
  setup hotspot remains available for ten minutes after boot.
- Parked mode stops repeated vehicle PID queries. Motion or charging voltage
  wakes acquisition. Wi-Fi shuts down between upload windows; the ESP32 uses
  short light-sleep intervals. Battery draw and wake reliability need measurement
  on your unit. A charger can keep it awake; a missing motion sensor plus low
  alternator voltage can miss a wakeup.
- Password-protected phone/browser setup, NVS-persisted Wi-Fi/receiver settings,
  NTP clock, phone clock setting, and visible OBD/storage/upload faults.
- Python receiver with SQLite persistence, authenticated reports, per-trip and
  daily CSV export for Excel, timezone support and undated-mileage reporting.
- Docker Compose for a home server such as mserver. No cellular plan is used.

## Destination choices

| Destination | Included now | Connection |
|---|---|---|
| Home server / NAS | Yes | Run the receiver; store its data directory on the chosen server disk |
| Excel | Yes, CSV files | Export daily, trip or raw-event CSVs; open/import them in Excel |
| Google Sheets | Adapter not yet configured | Have a server-side connector copy receiver reports to Sheets |
| Other software | Documented API | Implement the acknowledgment contract in `docs/PROTOCOL.md` |

The firmware URL is configurable without reflashing. It expects the Taxile
protocol, not an arbitrary spreadsheet sharing URL. Google OAuth, Apps Script,
Microsoft Graph and cloud account permissions are intentionally not configured
until the destination is chosen. The included receiver is fully usable on its own.

## Build

Use **PlatformIO** from the repository root. The official Freematics library is
vendored and versioned. No `config.h` is required.

```sh
python -m pip install platformio==6.2.0
pio run
```

The target uses Arduino ESP32 2.0.17, 80 MHz CPU, DIO flash, a 4 MB-compatible
partition layout, no PSRAM requirement, and USB serial at 115200 baud. Compatible
larger-flash original ESP32 units use the same initial 4 MB region. OTA is not
implemented; firmware updates use USB. This custom firmware does not implement
the factory Freematics Controller BLE protocol or code clearing.

Use `pio run -t upload` only after confirming the chip/hardware revision. It
replaces the factory application. Capture the original flash before the first
change if you want an exact restoration path; see `docs/SETUP.md`.

## Setup

See `docs/SETUP.md` for reference. When setting up interactively, complete one
step at a time and verify its result before proceeding. No Wi-Fi password needs
to be sent in chat or committed to Git.

On boot, USB serial prints a unique setup password. Join the `Taxile-xxxxxx`
hotspot and visit `http://192.168.4.1`. Sign in as `admin` with that password.
The same secret protects the hotspot and digest-authenticated setup page.
The password is not returned by the status endpoint. Use the page only on a
trusted network while parked. Physical USB access can display the setup password.

An endpoint URL can be left blank; local recording still works. Settings can
be saved only when the logger shows parked. To reopen the hotspot after its
ten-minute timeout, send `SETUP` followed by newline over USB serial.

## Persistence and time

Records live in `/outbox` on the card until acknowledged. Do not remove the card
while powered. Back up the receiver's entire `data` directory using a consistent
SQLite backup or while the receiver is stopped (include WAL files if copying live).
Do not delete/reformat an outbox to fix connectivity. A full or failing card stops
recording and raises a visible error; no data is silently overwritten.

After an unexpected reset, already-flushed events remain importable, while an
unfinished trip is shown as incomplete. A new boot creates a new trip identity.
The partially written final line can be lost. FAT32 and SD hardware cannot
promise zero loss on a power cut; a damaged filesystem needs offline repair.

NTP or a phone provides UTC. Later time anchors can date earlier records from
**the same uninterrupted boot**. Light sleep preserves that relationship. No
old timestamp is guessed across a full power loss. Undated mileage is retained
and explicitly excluded from daily dated totals. CSV trip rows show the time
quality and incomplete status. Local days default to `America/Chicago` and
midnight-spanning intervals are divided proportionally.

## Tests

```sh
python -m unittest discover -s tests -v
g++ -std=c++11 -Ifirmware/Taxile tests/native/test_mileage.cpp -o test-mileage
./test-mileage
pio run
```

See `docs/VALIDATION.md` for the software results and required vehicle checks.
`tools/report.py` remains available only for legacy 0.1 CSV logs; use the receiver
exports for the new 0.2 event format.

## License

Original Taxile code remains under the existing [Taxile Noncommercial License](LICENSE).
Free noncommercial use; no monetization without separate permission. Third-party
code retains its own licenses; see `THIRD_PARTY.md`.
