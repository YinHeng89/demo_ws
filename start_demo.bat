@echo off
REM Start uvicorn and open viewer in default browser (Windows)
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo Starting server: uvicorn server:app --host 0.0.0.0 --port 9000
start "Server" cmd /k "uvicorn server:app --host 0.0.0.0 --port 9000"

REM give server a short moment to start
timeout /t 1 /nobreak >nul

echo Opening viewer page in default browser...
start "" "http://127.0.0.1:9000/viewer"