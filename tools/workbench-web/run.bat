@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ai-prompts workbench launcher (local-only)
REM Starts web UI and opens your browser.

set ROOT=%~dp0
cd /d %ROOT%

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python not found on PATH.
  echo Install Python 3.10+ and ensure `python` works in Command Prompt.
  goto fail
)

where powershell >nul 2>nul
if errorlevel 1 (
  echo ERROR: PowerShell not found.
  goto fail
)

REM Pass optional args: first arg can override StartPort (e.g. run.bat 8790)
set START_PORT=%1
if "%START_PORT%"=="" set START_PORT=8787

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%run.ps1" -StartPort %START_PORT%
if errorlevel 1 goto fail
goto :eof

:fail
echo.
echo Workbench launcher failed.
echo.
pause
exit /b 1
