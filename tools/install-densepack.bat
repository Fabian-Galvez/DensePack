@echo off
rem Double-click launcher for install-densepack.ps1.
rem Windows opens a .ps1 file in an editor. This .bat runs the script with PowerShell.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-densepack.ps1"
echo.
pause
