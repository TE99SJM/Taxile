# Vehicle identity extension — schema 2

All newly emitted events carry schema=2 plus:

- `vin`: validated 17-character uppercase OBD-II VIN, or empty if unavailable.
- `vehicle_id`: VIN when known, otherwise `unknown-<boot_id>-t<trip>`.
- `vehicle_identification`: `vin` or `unknown`.

START/SAMPLE/END freeze identity for the entire trip. BOOT/CLOCK carry current connection metadata and cannot reassign mileage. A reconnect clears live VIN and rereads it. An acquisition link loss closes the previous trip before reconnect. Per-event identity survives SD buffering and upload retries, so moving the dongle cannot relabel queued records.

The receiver accepts schema 1 and 2. Schema 1 reports use `legacy-<device_id>-<boot_id>` with no inferred VIN. Known schema 2 vehicle ID must equal VIN. Conflicting identities in the same trip reject the complete incoming batch atomically. SQLite event payloads preserve identity without migrating old records. Daily/trip/raw CSV exports include vehicle columns; summary JSON adds a `vehicles` collection. Offline CSV reporting also groups by vehicle.

## Inherited transport details

# Taxile upload protocol v1

The firmware accepts any configured receiver URL that implements this contract.
The provided receiver uses `POST /v1/batches`. A Google Sheets sharing URL, Excel
file URL, or plain webhook without this acknowledgment contract will not work.

## Request

- `Authorization: Bearer <secret>` (at least 32 characters)
- `Content-Type: application/x-ndjson`
- `Content-Length` must be known; no chunked upload.
- `X-Taxile-Device`: immutable ESP32 device identifier
- `X-Taxile-Batch`: filename such as `<random-boot-id>-00000001.ndjson`
- Body: 1–60 JSON objects, one per line, including a final newline; at most 96 KB.

Each object contains:

| Field | Meaning |
|---|---|
| schema | Integer 1 |
| device_id | ESP32 MAC-derived stable identifier |
| boot_id | Random 128-bit ID for this uninterrupted runtime |
| seq, event_id | Increasing sequence and `<boot_id>-<seq>` |
| trip_id | `<boot_id>-t<number>`, empty before a trip |
| type | BOOT, CLOCK, START, SAMPLE or END |
| uptime_ms | Monotonic milliseconds since this boot, 64-bit |
| epoch_utc | Integer UTC seconds or null |
| speed_kph, rpm | OBD readings, -1 if unavailable |
| delta_miles | New estimated distance; nonzero only for SAMPLE |
| trip_miles | Diagnostic cumulative estimate, never sum this column |
| interval_ms | Sample interval, zero for non-samples |
| missing_ms | Cumulative trip time excluded from integration |
| calibration | Applied speed-distance multiplier |

Integrate only consecutive valid speed samples separated by at most five seconds.
`delta_miles`, not `trip_miles`, is the additive field. Event identities are
scoped to device and must be deduplicated across batches. Event bytes cannot be
changed after acceptance under the same identity.

## Required acknowledgment

Only after all events are validated and durably committed, return HTTP 200 with
`Content-Length` greater than 0 and less than 1024, containing:

```json
{"ok":true,"batch_id":"<exact request batch ID>","sha256":"<64 lowercase hex characters of SHA-256 of the exact body bytes>"}
```

An identical retry must return the same successful acknowledgment, even if the
first response was lost. Reusing a batch or event ID for different content must
return HTTP 409, without partially importing the batch. The supplied receiver
implements both deduplication levels in SQLite with full synchronous commits.
The firmware keeps the file on every failure or invalid acknowledgment.

No redirects are followed, so a token is never forwarded to another host. HTTPS
requires a configured CA certificate and a valid system clock; certificate
verification is never disabled. Self-hosted HTTP needs explicit opt-in and is
intended only for a trusted home LAN. No port forwarding is required.

## Read API

All except `/health` require the same bearer token. Reports can use
`?tz=America/Chicago` or another valid IANA timezone.

- `GET /health`: process health only, no trip data
- `GET /v1/summary`: daily and trip totals, incomplete trips, undated miles
- `GET /v1/daily.csv`: Excel-compatible daily totals
- `GET /v1/trips.csv`: trip totals, timestamps, missing time, completeness
- `GET /v1/events.csv`: raw records for audit or other integrations

A Sheets adapter can run on the receiver and authenticate with Google there.
Use device/event IDs or device/trip IDs as upsert keys; never blindly append a
whole exported report on every sync. Avoid making the device manage Google or
Microsoft OAuth credentials. The adapter itself is a later destination choice.

## Retention and recovery

Acknowledged files are removed from the card; back up the receiver database.
Incomplete `.open` files are recovered by firmware at boot. It preserves their
valid newline-terminated prefix and reports discarded partial tails. Original
files remain until the recovered file is finalized. FAT32 metadata or SD
controller damage cannot be solved purely by this application.

`python scripts/import_sd.py <copied-outbox-directory> --db <database>` imports
complete pending files without deleting the source. This uses the same server
validation and deduplication as online uploads. Legacy 0.1 CSV files remain
separate and can be summarized with `tools/report.py`.
