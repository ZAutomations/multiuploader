@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
 echo Setup failed. Read the error above.
 pause
 exit /b 1
)
echo Setup complete. Start the tool using RUN.bat in the main folder.
pause
