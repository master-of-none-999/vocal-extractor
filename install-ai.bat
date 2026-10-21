@echo off
cd /d "%~dp0"
echo Installing Demucs AI packages (this may take a few minutes)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -WithAI
echo.
pause
