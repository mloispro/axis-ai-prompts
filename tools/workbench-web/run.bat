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

REM Usage:
REM   run.bat                 -> background start (auto-port from 8787)
REM   run.bat 8790            -> background start (auto-port from 8790)
REM   run.bat stop            -> stop last-launched
REM   run.bat restart [8790]  -> stop then background start
REM   run.bat dev [8790] [noopen]   -> foreground dev server (uvicorn --reload)
REM   run.bat serve [8790] [noopen] -> foreground server (no reload)

set MODE=%1
set ARG2=%2
set ARG3=%3

set NOOPEN=
if /I "%ARG3%"=="noopen" set NOOPEN=-NoOpen

if /I "%MODE%"=="stop" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launcher.ps1" -Mode stop
  if errorlevel 1 goto fail
  goto :eof
)

if /I "%MODE%"=="restart" (
  set START_PORT=%ARG2%
  if "%START_PORT%"=="" set START_PORT=8787
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launcher.ps1" -Mode restart -StartPort %START_PORT%
  if errorlevel 1 goto fail
  goto :eof
)

if /I "%MODE%"=="dev" (
  set PORT=%ARG2%
  if "%PORT%"=="" set PORT=8787
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launcher.ps1" -Mode dev -Port %PORT% %NOOPEN%
  if errorlevel 1 goto fail
  goto :eof
)

if /I "%MODE%"=="serve" (
  set PORT=%ARG2%
  if "%PORT%"=="" set PORT=8787
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launcher.ps1" -Mode serve -Port %PORT% %NOOPEN%
  if errorlevel 1 goto fail
  goto :eof
)

set START_PORT=%MODE%
if "%START_PORT%"=="" set START_PORT=8787

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launcher.ps1" -Mode run -StartPort %START_PORT%
if errorlevel 1 goto fail
goto :eof

:fail
echo.
echo Workbench launcher failed.
echo.
pause
exit /b 1
