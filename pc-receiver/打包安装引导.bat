@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Build the installer/guide exe with PyInstaller. This file does NOT install anything by itself:
rem   pyinstaller must already be installed (pip install pyinstaller).
rem It bundles three files: the client exe, the uninstaller exe (both must be built first) and the
rem official ViGEmBus setup in the vendor folder.
rem --windowed: GUI only. No --uac-admin: the guide runs as a normal user, and only the driver
rem install step elevates (one UAC prompt). Copying files and making shortcuts need no admin.

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

if not exist "Xpad-joy.exe" (
    echo [ERROR] Xpad-joy.exe not found here. Build the client first, then build the installer.
    pause
    exit /b 1
)
if not exist "vendor\ViGEmBus_1.22.0_x64_x86_arm64.exe" (
    echo [ERROR] vendor\ViGEmBus_1.22.0_x64_x86_arm64.exe not found. Download it from
    echo         https://github.com/nefarius/ViGEmBus/releases (v1.22.0) and put it in vendor\.
    pause
    exit /b 1
)

if not exist "Xpad-joy-Uninstaller.exe" (
    echo [WARN] Xpad-joy-Uninstaller.exe not found here, so the guide cannot put an uninstaller
    echo        into the install folder. Build it first with the uninstaller build bat.
)

if not exist "vendor\platform-tools\adb.exe" (
    echo [WARN] vendor\platform-tools\adb.exe not found, so the guide cannot put adb into the
    echo        install folder. Copy adb.exe + AdbWinApi.dll + AdbWinUsbApi.dll from Android
    echo        platform-tools into vendor\platform-tools\ (only needed for the USB/ADB path).
)

echo [BUILD] pyinstaller --onefile --windowed --name Xpad-joy-Installer --clean installer.py
py -3 -m PyInstaller --onefile --windowed --name Xpad-joy-Installer --clean ^
    --add-data "Xpad-joy.exe;." --add-data "Xpad-joy-Uninstaller.exe;." ^
    --add-data "vendor\ViGEmBus_1.22.0_x64_x86_arm64.exe;." ^
    --add-data "vendor\platform-tools;platform-tools" installer.py
if errorlevel 1 (
    echo [ERROR] build failed. See the output above.
    pause
    exit /b 1
)

copy /y dist\Xpad-joy-Installer.exe Xpad-joy-Installer.exe >nul
echo [OK] Xpad-joy-Installer.exe ready next to this bat (Chinese title inside the window).
:end
pause
