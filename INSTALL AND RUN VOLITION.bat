@echo off
title Volition - Install and Run
cd /d "%~dp0"

echo.
echo ============================================
echo   Volition - first-time setup and launch
echo ============================================
echo.

if not exist "app\volition_demo_main.py" (
    echo [PROBLEM] This file cannot find the "app" folder next to it.
    echo.
    echo Fix: this file must stay inside the Volition folder, in the same place as the "app" folder.
    echo If you moved it, put it back. If you see a folder inside a folder, open the inner one.
    echo.
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo [PROBLEM] Python is not installed, or was installed without "Add python.exe to PATH".
    echo.
    echo Fix: follow STEP 1 in README.md, then double-click this file again.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating a private Python folder for Volition. This happens once.
    python -m venv .venv
    if errorlevel 1 (
        echo [PROBLEM] Could not create the Python folder.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\volition_installed.txt" (
    echo.
    echo Downloading what Volition needs. This happens once and can take a few minutes.
    echo Please wait and do not close this window.
    echo.
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [PROBLEM] The download failed. Check that you are connected to the internet,
        echo then double-click this file again.
        pause
        exit /b 1
    )
    echo installed > ".venv\volition_installed.txt"
)

echo.
echo Starting Volition...
echo.
python "app\volition_demo_main.py"

echo.
echo Volition has closed. If you saw an error above, see "If something goes wrong" in README.md.
pause
