@echo off
rem Double-click launcher that removes DensePack: right-click entry, startup shortcut, hotkey.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-densepack.ps1" -Remove
echo.
pause
