@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Build the client exe with PyInstaller. This file does NOT install anything by itself:
rem   pyinstaller must already be installed (pip install pyinstaller).
rem --windowed: only the GUI window, no black console window. The source client.py stays
rem in this folder unchanged. Errors that used to go to the console are written to
rem Xpad-joy.log next to the exe (see say() in client.py).

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] py launcher not found, cannot build.
    pause
    exit /b 1
)

py -3 -c "import PyInstaller" >nul 2>nul || (
    echo [ERROR] pyinstaller not installed. Run: pip install pyinstaller
    pause
    exit /b 1
)

echo [BUILD] pyinstaller --onefile --windowed --name Xpad-joy --clean client.py
py -3 -m PyInstaller --onefile --windowed --name Xpad-joy --clean client.py
if errorlevel 1 (
    echo [ERROR] build failed. See the output above.
    pause
    exit /b 1
)

copy /y dist\Xpad-joy.exe Xpad-joy.exe >nul
echo [OK] Xpad-joy.exe ready next to this bat. The launcher bat (qi dong ke hu duan.bat) uses it automatically.
:end
pause
