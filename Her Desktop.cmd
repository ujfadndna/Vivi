@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_desktop.ps1" %*
if errorlevel 1 (
  echo.
  echo Vivi failed to start. See the message above.
  pause
)
