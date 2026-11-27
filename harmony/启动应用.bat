@echo off
rem Start Xpad-joy on the phone through the hdc debug channel.
rem On HarmonyOS NEXT the desktop icon of a debug-signed app installed outside
rem AppGallery is redirected to the system "App info" page, so use this while testing.
rem DevEco "Run" uses the same debug channel and still works.

set HDC=hdc
if exist "D:\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe" set HDC="D:\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe"

%HDC% list targets
%HDC% shell aa start -a EntryAbility -b com.xpad.joy
