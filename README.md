# Taxile — Freematics mileage logger

A self-hosted, noncommercial mileage logger designed for the **2018 Ram 1500** using a **Freematics ONE+ (ESP32)** OBD-II dongle.

> **Prototype:** Firmware is not yet validated on the actual truck/dongle. Verify hardware version, OBD support, clock and distance against the dash before relying on logs for taxes.

## Features
- Records engine-on trips and vehicle speed from standard Mode 01 OBD-II PIDs (RPM 0x0C, speed 0x0D).
- Estimates distance by integrating speed over *valid* consecutive samples; this is **not the vehicle's odometer**.
- Stores durable, append-only CSV events on microSD, including individual interval mileage and trip start/end markers.
- Starts a protected local Wi-Fi hotspot and serves a status page + downloadable CSV at `http://192.168.4.1/`.
- Optionally joins home Wi-Fi for NTP UTC synchronization. When disconnected without previously synchronized time, records are marked `time_valid=0` and cannot be assigned to a calendar day.
- The local webpage can sync the UTC clock from your phone or laptop (requires visiting the page and tapping **Sync clock**).
- Python offline reporting summarizes daily and trip miles from the downloaded CSV; no accounts, GPS tracking, or cloud services.

## Hardware
**Required:** Freematics ONE+ ESP32 (not the original AVR Freematics ONE), compatible microSD formatted FAT32, 2018 Ram 1500 with OBD-II. Optional: internet-connected Wi-Fi at home for automatic NTP time sync. No external GPS required.

## Firmware installation (Arduino IDE)
1. Install ESP32 Arduino board support and the official **FreematicsPlus** library from https://github.com/stanleyhuangyc/Freematics/tree/master/libraries/FreematicsPlus (the library has associated files and dependencies—follow the Freematics ONE+ developer guide).
2. Copy `firmware/Taxile/config.example.h` to `firmware/Taxile/config.h` and change the hotspot password (at least 8 characters) and optional Wi-Fi details.
3. Open `firmware/Taxile/Taxile.ino` in Arduino IDE; select the ESP32 board and correct COM port according to your specific Freematics hardware revision. Compile and upload over USB.
4. Insert a FAT32 microSD. Plug into the truck with ignition on. Open the serial monitor at 115200 baud and verify `OBD connected`, `SD ready`, and speed/RPM readings before driving.
5. Connect phone/laptop to hotspot `Taxile-Ram` using your password. Visit `http://192.168.4.1/`. Use **Sync clock**, then download `/log.csv`. If configured for home Wi-Fi, it also attempts automatic NTP.
6. On a computer with Python 3.9+, run `python tools/report.py log.csv` or `python tools/report.py log.csv --tz America/Chicago --out daily.csv`.

## Limitations and validation
- OBD speed is an integer in km/h, read every ~2 seconds; integration can differ from odometer due to tire size, low speeds, stale samples and ignition cycles. Verify against a known route or beginning/ending dash odometer. For tax records, document business purpose and start/end odometer separately.
- Clock time is UTC only; browser time or Wi-Fi NTP is necessary after a full restart to get calendar dates. No timezone is stored on-device; the reporter converts UTC to your chosen timezone.
- Missing OBD samples, SD errors, or interrupted power can cause undercounting. No backfilling is fabricated.
- CSV logs are append-only; keep backups. The web UI provides read/download, not remote deletion.
- With ignition off the device may remain powered by the diagnostic connector. Unplug if extended parking drains the battery; a future low-power mode is recommended.
- Only use the device's Wi-Fi while parked. Do not interact with the interface while driving.
- CSV files can contain trip history; do not publish raw logs.

## CSV schema
`event,boot_id,trip_id,epoch_utc,time_valid,uptime_ms,rpm,speed_kph,delta_miles,trip_miles`

`delta_miles` is measured over the preceding valid sampling interval. Reports sum these deltas and avoid treating speed as a lifetime odometer. Multiple CSV exports can be concatenated, but deduplicate repeated rows first.

## License
Taxile's original code is under the [Taxile Noncommercial License](LICENSE): free for personal, educational, and other noncommercial use, including modifications and redistribution with attribution. **Commercial exploitation is prohibited without separate written permission.** This is source-available, *not* an OSI-approved open-source license. The independently obtained Freematics dependencies retain their own licenses; this license does not supersede them.
