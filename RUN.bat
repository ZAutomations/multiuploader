@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
 call "%~dp0setup\setup.bat"
 if errorlevel 1 exit /b 1
)
set "PYTHONPATH="
"%~dp0.venv\Scripts\python.exe" "%~dp0youtube_uploader_gui.py"
if errorlevel 1 pause
