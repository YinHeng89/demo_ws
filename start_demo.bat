@echo off
REM start_demo.bat - 简化版：只启动服务端 (uvicorn server:app) 与 Qt 客户端 (client_qt.py)

SETLOCAL ENABLEDELAYEDEXPANSION
set "SCRIPT_DIR=%~dp0"
@echo off
REM start_demo.bat - Simple launcher: starts server (uvicorn server:app) and client (client.py)

SETLOCAL ENABLEDELAYEDEXPANSION
set "SCRIPT_DIR=%~dp0"
set "SCREEN_FLAG="
set "USE_SCREEN="

REM This launcher no longer prompts for FPS/Resolution. Defaults below are used.
REM If you want to override, run client.py directly with command-line args.

REM Prompt for FPS (default 15)
set /p "FPS=Enter FPS [30]: "
if "%FPS%"=="" set "FPS=30"
set "DEVICE=0"
set "WIDTH=640"
set "HEIGHT=480"
set "FMT=jpg"
REM Prompt for quality (default 80)
set /p "QUALITY=Enter quality (10-100) [80]: "
if "%QUALITY%"=="" set "QUALITY=80"

REM Ask whether to use screen capture (keep this simple)
set /p "USE_SCREEN=Use screen capture instead of camera? (y/N): "
if /I "!USE_SCREEN!"=="Y" (
	set "SCREEN_FLAG=--screen"
) else (
	set "SCREEN_FLAG="
	REM Prompt for camera device index when using camera
	set /p "DEVICE=Enter camera device index [0]: "
	if "%DEVICE%"=="" set "DEVICE=0"
)

echo Starting server: uvicorn server:app --host 0.0.0.0 --port 9000
start "Server" cmd /k "cd /d "%SCRIPT_DIR%" && uvicorn server:app --host 0.0.0.0 --port 9000"

REM Wait a moment for server to start
timeout /t 1 /nobreak >nul

echo Starting client (client.py) with parameters: FPS=%FPS% Device=%DEVICE% Resolution=%WIDTH%x%HEIGHT% Format=%FMT% Quality=%QUALITY% Screen=!USE_SCREEN!
start "Client" cmd /k "cd /d "%SCRIPT_DIR%" && python client.py --uri ws://localhost:9000/ws/stream --fps %FPS% --device %DEVICE% --width %WIDTH% --height %HEIGHT% --format %FMT% --quality %QUALITY% !SCREEN_FLAG!"

endlocal

REM Note: Server and client can be run independently; this script is a convenience helper.