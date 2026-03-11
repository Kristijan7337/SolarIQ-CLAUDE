@echo off
cd /d "%~dp0"
echo ================================
echo   SolarIQ - Sinkronizacija...
echo ================================
py -3.11 hep_sync.py
py -3.11 fs_sync.py
start "" /b py -3.11 server.py
timeout /t 3 /nobreak > nul
start "" http://localhost:5000
exit
