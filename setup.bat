@echo off
:: setup.bat — Housing Watcher setup for Windows 11 (local tuning)
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

echo === Housing Watcher Windows Setup ===
echo.

:: ── 1. Check Python 3.12 ─────────────────────────────────────────────────
echo [1/3] Checking Python 3.12...
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.12 not found. Install from https://python.org and ensure it's registered with the launcher.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('py -3.12 --version') do echo     Found: %%v

:: ── 2. Create .venv and install deps ─────────────────────────────────────
echo [2/3] Setting up .venv...
if not exist "%VENV_DIR%" (
    py -3.12 -m venv "%VENV_DIR%"
    echo     .venv created.
) else (
    echo     .venv already exists — skipping creation.
)

echo     Installing dependencies...
"%VENV_DIR%\Scripts\pip.exe" install --quiet --upgrade pip
"%VENV_DIR%\Scripts\pip.exe" install --quiet -r "%SCRIPT_DIR%requirements.txt"
echo     Dependencies installed.

:: ── 3. .env check ─────────────────────────────────────────────────────────
echo [3/3] Checking .env...
if not exist "%SCRIPT_DIR%.env" (
    echo ERROR: .env file not found at %SCRIPT_DIR%.env
    echo        Copy .env.example or create one before running.
    pause
    exit /b 1
)
echo     .env found.

echo.
echo === Setup complete ===
echo.
echo   For selector tuning, make sure your .env has:
echo       HEADLESS=false
echo       CHROMEDRIVER_PATH= (leave empty or set to local path)
echo       STATE_FILE and LOG_FILE can be relative paths for local use
echo.
echo   Run the watcher:
echo       %VENV_DIR%\Scripts\python.exe %SCRIPT_DIR%watcher.py
echo.
echo   Or use the shortcut:
echo       run.bat
echo.

:: Create a convenience run.bat
echo @echo off > "%SCRIPT_DIR%run.bat"
echo "%VENV_DIR%\Scripts\python.exe" "%SCRIPT_DIR%watcher.py" >> "%SCRIPT_DIR%run.bat"
echo pause >> "%SCRIPT_DIR%run.bat"
echo     run.bat created.

pause
