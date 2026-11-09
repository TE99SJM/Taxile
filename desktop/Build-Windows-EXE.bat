@echo off
cd /d "%~dp0"
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.11.1
if errorlevel 1 (pause & exit /b 1)
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --name Taxile-PC taxile_pc.py
pause
