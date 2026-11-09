# Third-party source and build dependencies

`lib/FreematicsPlus/` is a vendored copy of the official FreematicsPlus
library from https://github.com/stanleyhuangyc/Freematics at commit
`9b0a68d89ac14c6fb6e63bdc2f28959a8a73ee9d` (retrieved 2026-11-09 UTC).
Its copyright and license notices are retained in the individual files.
The main library identifies itself as distributed under the BSD license;
embedded third-party drivers retain their respective notices.
Local compatibility patch: rename the Freematics `HTTPClient` base class to
`FreematicsHTTPBase` in FreematicsNetwork.h/.cpp to avoid collision with the
ESP32 Arduino HTTPClient class. No transport logic is changed.

Taxile's noncommercial license applies to Taxile code, not these dependencies.

The reproducible PlatformIO target pins espressif32 6.9.0 (Arduino ESP32 2.0.17),
ArduinoJson 6.21.5, and uses PlatformIO Core 6.2.0 for validation. Each dependency
retains its upstream license. No Wi-Fi, server or personal credentials are bundled.

Hardware API references:
- https://freematics.com/pages/products/freematics-one-plus/guide/
- https://freematics.com/products/freematics-one-plus/
- https://github.com/stanleyhuangyc/Freematics/tree/master/libraries/FreematicsPlus
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/preferences.html
- https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/sleep_modes.html
