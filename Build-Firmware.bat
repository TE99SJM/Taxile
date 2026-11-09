@echo off
cd /d "%~dp0"
py -3 -m pip install platformio==6.2.0
if errorlevel 1 (pause & exit /b 1)
py -3 -m platformio run
pause
