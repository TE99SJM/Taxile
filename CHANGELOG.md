# Desktop touch update (firmware remains 0.4.0)

- Adds large touch controls and text fields, two-column actions and a scrollable layout.
- Adds a built-in touch keyboard, password visibility toggle and full-screen toggle.
- Adds swipeable results, wide scrollbars and large result paging buttons.
- Replaces the code-clear confirmation with a touch-sized modal.
- Preserves diagnostics protocol and existing 0.4.0 firmware compatibility.

# 0.4.0

- Reads VIN automatically at every OBD connection and freezes it per trip.
- Keeps unknown identities and historical untagged mileage separate.
- Closes trips at OBD communication loss before identifying the next vehicle.
- Adds vehicle columns to daily/trip/raw CSV, per-vehicle summary totals and PC/web status.
- Validates schema 2 identity and rejects mid-trip identity changes atomically.
- Adds native VIN/swap tests and server tests for multi-vehicle reporting.

# 0.3.0

- Adds Taxile PC, a native Tk desktop client with Windows launch/build scripts.
- Reads stored generic OBD-II emissions DTCs with standard P/C/B/U formatting.
- Sends a confirmed Mode 04 clear and checks for a positive ECU acknowledgement.
- Uses existing Digest login and a fresh CSRF token for every operation.
- Serializes diagnostics with vehicle acquisition; requires zero RPM and speed.
- Handles CAN count bytes, legacy responses, multiple replies and adapter failures.
- Extends the awake/radio session while servicing diagnostics.
- Preserves inherited mileage queue, receiver, reporting and configuration.
- Includes native parser tests, desktop transport tests and Windows/firmware CI.

Hardware target: original ESP32 UART-link ONE+. No Bluetooth transport, ABS/airbag scanning or manufacturer-specific modules in this release. USB remains the flash/setup connection. Windows EXE must be built on Windows; Python launcher is supplied.
