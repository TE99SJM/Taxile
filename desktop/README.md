# Taxile PC 0.4.0

Windows desktop client for the matching ONE+ firmware. Retains the existing mileage receiver and Wi-Fi settings workflow. This is a Python/Tk application; a precompiled Windows EXE is not included. Run `Start-Taxile.bat` with Python 3 installed, or build an EXE on Windows with `Build-Windows-EXE.bat`. Installation/build needs internet; normal local diagnostics does not.

## Connect

1. Flash matching firmware after confirming original ESP32 UART-link ONE+ hardware. Keep the device connected to the vehicle for diagnostics. USB alone cannot read a vehicle.
2. Obtain the generated admin password in USB serial at 115200 baud. No default password is assumed. Existing NVS settings/password survive normal uploads.
3. While safely parked, ignition ON, engine OFF, restart the ONE+ to open its ten-minute `Taxile-xxxxxx` hotspot. Join it using the admin password. Use address `192.168.4.1` in the desktop app. Joining this hotspot can disconnect normal internet.
4. Alternatively, use the existing setup webpage to configure home Wi-Fi. Find its address in your router or `/api/status`, then enter that address in the app while both devices are on the same LAN. This retains normal home internet access. Reachability depends on vehicle location and the logger's radio windows.
5. Enter the admin password and click Connect / Status, then Read codes. Save the result before clearing. Clear codes requires an explicit confirmation and a second Read codes operation to check remaining codes.

Successful diagnostics extend the awake period for two minutes. Boot hotspot is ten minutes, parked sync window three minutes. Power-cycle the ONE+ or send `SETUP` over USB serial to reopen setup when the radio is asleep. This release does not add Bluetooth or USB diagnostic transport; USB is used for setup/flashing.

## Scope

Stored generic emissions-related OBD-II DTCs (Mode 03) and ECU-acknowledged clear (Mode 04). The app does not scan ABS, airbags, body modules, pending Mode 07 or permanent Mode 0A codes. Permanent codes may remain after a clear. No vehicle manufacturer-specific PID or code definition database is claimed. Clearing also resets readiness monitors and freeze-frame information. The firmware verifies zero RPM and speed; a failed verification blocks both operations.

Digest authentication and a fresh CSRF token protect commands. Password stays in memory. Local HTTP is not encrypted; use only a trusted LAN or the protected hotspot. Commands are never automatically retried by this client. An acknowledgement means an ECU replied to Mode 04; it is not proof that every module cleared or that a fault was repaired.

## Developer validation

From the package root: `python -m unittest discover -s tests -v`. Native parser tests: `g++ -std=c++17 tests/native/test_diagnostics.cpp -o test_diagnostics` then run it. Native mileage tests need `-I firmware/Taxile`.

The production parser handles header-free ELM spaced hex, multiple ECU replies, numbered continuation lines, CAN DTC counts and duplicate codes. It rejects missing acknowledgements, truncated codes and common adapter errors rather than showing an empty successful scan. Actual adapter response compatibility and Windows UI behavior need device testing.

Vehicle VIN and the frozen trip VIN are shown in Connect / Status. Mileage reports and CSV exports are grouped by vehicle on the receiving server. No last-vehicle fallback is used when the ECU VIN is unavailable.

## Touch controls

The desktop app now uses large buttons and text fields, a two-column action grid, a vertically scrollable layout for portrait/landscape windows, wide scrollbars, swipeable results, and large result paging buttons. Tap a connection field and then **Touch keyboard** for a built-in keyboard with letters, Shift, symbols, Space and Backspace. Show password has a large toggle. Full screen toggles tablet mode; F11 also toggles it and Escape exits it. Clearing codes uses a separate confirmation with large Cancel and Confirm buttons.

This desktop app targets Windows tablets (and desktop Linux/macOS with Tk). It does not run as an Android or iPad app. No new firmware flash is required for this layout update; it still connects to Taxile 0.4.0 firmware. UI syntax and existing client tests were checked; physical touch gestures, Windows keyboard behavior and tablet DPI/layout still need validation on the actual tablet.
