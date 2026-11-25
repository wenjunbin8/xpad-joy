@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [NOTE] The exe is windowed (GUI only, no black console window). Errors and events are written to Xpad-joy.log next to the exe.
echo [NOTE] Window layout: left card = QR + address, right card = status / source / packets / round-trip / key detection, one line for the latest event.
echo [NOTE] USB path = ADB tunnel, TCP only. adb reverse runs automatically at startup and every 30 s; the phone must use 127.0.0.1 with this port.
echo [NOTE] Wi-Fi path still uses UDP; both paths can be used at the same time.

rem ---- 1) Prefer the packaged exe. Source (client.py) stays in this folder and still works. ----
if exist "%~dp0Xpad-joy.exe" (
    echo [START] Xpad-joy.exe
    "%~dp0Xpad-joy.exe" %*
    pause
    exit /b 0
)

rem ---- 2) No exe here: run the source with Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [ERROR] Python 3 not found and no Xpad-joy.exe in this folder.
    echo         Either copy Xpad-joy.exe here, or install Python 3.10+ and check "Add Python to PATH".
    pause
    exit /b 1
)

rem ---- ViGEmBus driver is already installed: only check the package, never pip install anything.
rem ---- Chinese text stays in client.py; cmd.exe mis-parses Chinese inside a .bat, so this file is ASCII only.
%PY% -c "import vgamepad" >nul 2>nul || echo [NOTE] vgamepad missing (only the virtual gamepad is affected; the info panel still works): pip install vgamepad
%PY% -c "import qrcode" >nul 2>nul || echo [NOTE] qrcode missing: the window shows only the text address (no QR picture)

echo [START] %PY% client.py
%PY% client.py %*

pause
