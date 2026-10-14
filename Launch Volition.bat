@echo off
title Volition — Biosignal Control System
color 0A

REM ── Locate the script relative to this .bat file ──────────────────
set "DIR=%~dp0"
set "VENV=%DIR%..\\.venv"
set "SCRIPT=%DIR%volition_main.py"

REM ── Check venv exists ─────────────────────────────────────────────
if not exist "%VENV%\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at:
    echo         %VENV%
    echo.
    echo Make sure this .bat file is inside NPG-Lite-SNES\
    echo and the .venv folder is one level up in NPG-Lite-SNES-main\
    pause
    exit /b 1
)

REM ── Activate venv and launch ───────────────────────────────────────
call "%VENV%\Scripts\activate.bat"
cd /d "%DIR%"

echo  _   _       _ _ _   _             
echo ^| ^| ^| ^|___  ^| (_) ^|_(_) ___  _ __  
echo ^| ^|^| / _ \ ^| ^| ^| __^| ^|/ _ \^| '_ \ 
echo ^|  _  (_) ^|^| ^| ^| ^|_^| ^| (_) ^| ^| ^| ^|
echo ^|_^| ^|_\___/ ^|_^|_^\__^|_^\___/^|_^| ^|_^|
echo.
echo Adaptive Biosignal Control System
echo ----------------------------------
echo.

python "%SCRIPT%"

REM ── If Python exits with error, keep window open ───────────────────
if errorlevel 1 (
    echo.
    echo [!] Volition closed with an error. See above for details.
    echo     Common fixes:
    echo       - Make sure NPG Lite is powered on before connecting
    echo       - Run: pip install pynput   (for HID support)
    echo       - Run: pip install tflite-runtime   (for TFLite)
    pause
)
