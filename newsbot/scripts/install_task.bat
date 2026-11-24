@echo off
rem Registers a Windows scheduled task "Newsbot" that runs scripts\run.bat every 30 minutes.
rem Remove it again with:  schtasks /Delete /TN Newsbot /F
schtasks /Create /TN "Newsbot" /TR "\"%~dp0run.bat\"" /SC MINUTE /MO 30 /F
if %errorlevel%==0 echo Task "Newsbot" created - runs every 30 minutes.
