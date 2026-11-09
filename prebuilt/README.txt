Taxile 0.4.0 — compiled original ESP32 UART-link Freematics ONE+ images.

Compile verified; physical hardware and vehicle testing outstanding.
NOT for ESP32-C3, AVR ONE, or unverified SPI-only hardware.
Confirm chip/hardware and back up the entire original flash first.
Do not erase flash indiscriminately: existing NVS holds settings/passwords.
Prefer PlatformIO upload from source after hardware identification.

Separate images and standard build offsets:
bootloader.bin  0x1000
partitions.bin  0x8000
boot_app0.bin   0xe000
firmware.bin    0x10000

Do not write firmware.bin at address zero. This is not a full-device backup.
No compiled Windows EXE is included. Use desktop/Start-Taxile.bat (Python 3),
or build on Windows using desktop/Build-Windows-EXE.bat.
