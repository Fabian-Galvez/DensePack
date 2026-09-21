@echo off
rem Double-click launcher for install-densepack.ps1.
rem Windows opens .ps1 files in an editor by design, so this .bat starts it properly.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-densepack.ps1"
echo.
pause
