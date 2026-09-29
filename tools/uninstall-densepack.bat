@echo off
rem Double-click launcher that removes the DensePack right-click entry, startup shortcut, hotkey and reading card.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-densepack.ps1" -Remove
echo.
pause
