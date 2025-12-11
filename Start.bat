@echo off
setlocal EnableExtensions DisableDelayedExpansion
title App Launcher (portable)

REM --- App root (this folder) ---
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

REM --- Prefer per-project venv ---
set "VENV_DIR=%APP_DIR%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

REM Optional override: set PY_EXE=C:\Users\...\Python313\python.exe before calling
set "PY_CMD="

REM 1) Use venv if present
if exist "%VENV_PY%" set "PY_CMD=%VENV_PY%"

REM 2) Else create venv with a real Python (avoid WindowsApps alias)
if not defined PY_CMD (
  if defined PY_EXE if exist "%PY_EXE%" set "SYS_PY=%PY_EXE%"
)
if not defined SYS_PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%~fP | find /I "WindowsApps" >nul
    if errorlevel 1 set "SYS_PY=%%~fP"
  )
)
if not defined SYS_PY (
  REM Last ditch: common python.org install location (adjust if yours differs)
  if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "SYS_PY=%LocalAppData%\Programs\Python\Python313\python.exe"
)

if not defined PY_CMD (
  if not defined SYS_PY (
    echo [ERROR] No real Python found. Install from python.org or set PY_EXE, then retry.
    pause
    exit /b 1
  )
  echo [SETUP] No venv found, creating...
  "%SYS_PY%" -m venv "%VENV_DIR%" || (echo [ERROR] venv creation failed& pause& exit /b 1)
  set "PY_CMD=%VENV_PY%"
)

REM --- Ensure dependencies once venv exists ---
if exist "%APP_DIR%requirements.txt" (
  echo [SETUP] Ensuring dependencies from requirements.txt...
  "%PY_CMD%" -m pip install --upgrade pip setuptools wheel
  "%PY_CMD%" -m pip install -r "%APP_DIR%requirements.txt"
)

REM --- Network env from caller (mini_server_manager passes HOST/PORT in env) ---
if "%PORT%"=="" set "PORT=8050"
if "%HOST%"=="" set "HOST=0.0.0.0"

REM Make these visible to Python app that reads env
set "FLASK_RUN_PORT=%PORT%"
set "FLASK_RUN_HOST=%HOST%"

REM --- Start the app ---
if exist "%APP_DIR%app.py" (
  echo [RUN] Starting app.py with "%PY_CMD%"  (HOST=%HOST% PORT=%PORT%)
  "%PY_CMD%" "%APP_DIR%app.py"
  goto :eof
)

REM If your project uses a different entrypoint, add more fallbacks here
if exist "%APP_DIR%run.py" (
  echo [RUN] Starting run.py with "%PY_CMD%"  (HOST=%HOST% PORT=%PORT%)
  "%PY_CMD%" "%APP_DIR%run.py"
  goto :eof
)

echo [INFO] No app.py or run.py found in "%APP_DIR%".
echo        Update Start.bat or set "cmd" in services.json accordingly.
pause
