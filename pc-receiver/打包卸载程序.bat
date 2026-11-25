@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Build the uninstaller exe with PyInstaller. This file does NOT install anything by itself:
rem   pyinstaller must already be installed (pip install pyinstaller).
rem GUI only (--windowed); no admin needed for deleting files in the install folder and the desktop
rem shortcut (if the install folder needs admin, the uninstaller logs the failure instead).

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

set ICONFLAG=
if exist "icon.ico" (
    set ICONFLAG=--icon "icon.ico" --add-data "icon.ico;."
) else (
    echo [WARN] icon.ico not found here. Run tools\make_icon.py once; without it the exe keeps the
    echo        default icon.
)

echo [BUILD] pyinstaller --onefile --windowed --name Xpad-joy-Uninstaller --clean [icon] uninstaller.py
py -3 -m PyInstaller --onefile --windowed --name Xpad-joy-Uninstaller --clean %ICONFLAG% uninstaller.py
if errorlevel 1 (
    echo [ERROR] build failed. See the output above.
    pause
    exit /b 1
)

copy /y dist\Xpad-joy-Uninstaller.exe Xpad-joy-Uninstaller.exe >nul
echo [OK] Xpad-joy-Uninstaller.exe ready next to this bat.
:end
pause
