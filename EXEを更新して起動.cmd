@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update_and_start.ps1"
if errorlevel 1 (
  echo.
  echo FastComment could not start. See the error above.
  pause
)
