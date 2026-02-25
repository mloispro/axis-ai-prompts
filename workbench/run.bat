@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ai-prompts workbench launcher (local-only)
REM Starts web UI and opens your browser.

set ROOT=%~dp0
cd /d %ROOT%

if not exist .venv\Scripts\python.exe (
  echo Missing venv. Creating it now...
  python -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1
  .venv\Scripts\pip.exe install -r requirements.txt || exit /b 1
)

set PORT=8787
:find_port
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  set /a PORT=%PORT%+1
  goto find_port
)

set URL=http://127.0.0.1:%PORT%/
echo Starting ai-prompts workbench at %URL%

start "ai-prompts workbench" "%URL%"

.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port %PORT%

