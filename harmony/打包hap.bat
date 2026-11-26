@echo off
chcp 65001 >nul
setlocal
rem Xpad-joy HarmonyOS (hap) build. Pure ASCII on purpose: hvigor rejects a
rem project path that contains non-ASCII characters, so the repo must live on an
rem ASCII path (D:\project\xpad-joy), not under a Chinese folder name.
set "DEVECO=D:\Huawei\DevEco Studio"
set "DEVECO_SDK_HOME=%DEVECO%\sdk"
set "PATH=%DEVECO%\tools\node;%DEVECO%\jbr\bin;%PATH%"
cd /d "%~dp0"

"%DEVECO%\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=entry@default -p buildMode=debug --no-daemon assembleHap

echo.
echo Output: entry\build\default\outputs\default\entry-default-unsigned.hap
echo Unsigned on purpose: no signingConfigs profile is configured yet.
echo For a real device you need a debug certificate + profile (DevEco auto-signing,
echo which adds the device UDID), then hvigor will sign the hap too.
