@echo off
rem Watch hilog while you tap the app icon on the phone.
rem Run this first, then tap the icon. What you see decides the diagnosis:
rem   - a line "startAbility ... EntryAbility"  = normal launch (app opens)
rem   - a line about appinfo / accesscontrol / settings = the redirect to the App info page
set HDC=hdc
if exist "D:\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe" set HDC="D:\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe"

%HDC% list targets
%HDC% shell hilog -r
echo Tap the app icon on the phone now (Ctrl+C to stop)...
%HDC% shell "hilog | grep -iE \"com.xpad.joy|appinfo|accesscontrol|PhoneAppManager|hmos.settings|startAbility\""
