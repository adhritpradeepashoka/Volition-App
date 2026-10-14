@echo off
REM Build Volition App.exe — IMU + Kasa enabled demo build
REM =========================================================
REM Run this from inside the Volition/NPG-Lite-SNES project folder.
REM
REM Output: dist\Volition App.exe
REM
REM This build expects:
REM   - volition_demo.spec
REM   - volition_demo_main.py
REM   - ble_manager.py
REM   - ble_connection.py
REM and installs the extra smart-device dependency used by the app:
REM   - python-kasa

echo.
echo ============================================
echo   Building Volition App.exe
echo ============================================
echo.

set "DIR=%~dp0"
set "VENV=%DIR%..\.venv"

if not exist "%VENV%\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found at:
    echo         %VENV%
    echo.
    echo Run this script from inside the NPG-Lite-SNES folder.
    pause
    exit /b 1
)

call "%VENV%\Scripts\activate.bat"
cd /d "%DIR%"

echo Checking for required Python packages...
python -c "import bleak; print('  bleak: OK')" >nul 2>&1
if errorlevel 1 (
    echo Installing bleak...
    pip install bleak
    if errorlevel 1 (
        echo [ERROR] Could not install bleak.
        pause
        exit /b 1
    )
)

python -c "import kasa; print('  python-kasa: OK')" >nul 2>&1
if errorlevel 1 (
    echo Installing python-kasa...
    pip install python-kasa
    if errorlevel 1 (
        echo [ERROR] Could not install python-kasa.
        pause
        exit /b 1
    )
)

echo.
echo Checking for PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Could not install PyInstaller.
        pause
        exit /b 1
    )
)

if not exist "volition_demo_main.py" (
    echo.
    echo [ERROR] volition_demo_main.py was not found in:
    echo         %DIR%
    echo.
    echo Replace your existing main file with the integrated
    echo volition_demo_main.py before building.
    pause
    exit /b 1
)

if not exist "volition_demo.spec" (
    echo.
    echo [ERROR] volition_demo.spec was not found in:
    echo         %DIR%
    echo.
    pause
    exit /b 1
)

if not exist "ble_manager.py" (
    echo.
    echo [ERROR] ble_manager.py was not found in:
    echo         %DIR%
    echo.
    echo Copy the integrated ble_manager.py into the project folder before building.
    pause
    exit /b 1
)

if not exist "ble_connection.py" (
    echo.
    echo [ERROR] ble_connection.py was not found in:
    echo         %DIR%
    echo.
    echo Copy the integrated ble_connection.py into the project folder before building.
    pause
    exit /b 1
)

echo.
echo Verifying Volition BLE modules...
python -c "import ble_connection, ble_manager; print('  ble_connection + ble_manager import successfully.')"
if errorlevel 1 (
    echo [ERROR] Volition BLE modules could not be imported.
    echo Check that bleak is installed and the files are in this folder.
    pause
    exit /b 1
)

echo.
echo Required packages are present:
python -c "import bleak, kasa; print('  bleak + python-kasa import successfully.')"

echo.
echo Building... this will take a few minutes on first run.
echo Full output is being saved to build_log.txt as it runs.
echo.

pyinstaller volition_demo.spec --clean --noconfirm > build_log.txt 2>&1
set BUILD_RESULT=%errorlevel%

if %BUILD_RESULT% neq 0 (
    echo.
    echo [!] Build failed. Full output saved to build_log.txt
    echo     Common issues:
    echo       - Missing TensorFlow/TFLite runtime: pip install tensorflow
    echo       - Missing dependency: pip install bleak python-kasa
    echo       - Antivirus blocking PyInstaller temp files
    echo       - Outdated hook package: pip install --upgrade pyinstaller-hooks-contrib
    echo.
    echo Showing the last 50 lines of the error below:
    echo ============================================
    powershell -Command "Get-Content build_log.txt -Tail 50"
    echo ============================================
    echo.
    echo Full log saved at: %DIR%build_log.txt
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete!
echo   Output: dist\Volition App.exe
echo ============================================
echo.
echo The EXE now contains:
echo   - Existing EEG/EMG Volition processing
echo   - Optional NPG Lite IMU spatial targeting
echo   - Kasa smart-device control
echo.
echo You can copy "Volition App.exe" anywhere and run it directly.
echo No Python or venv is required on the destination machine.
echo.
pause
