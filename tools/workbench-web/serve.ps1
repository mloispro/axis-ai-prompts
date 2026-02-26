param(
    [int]$Port = 8787,
    [string]$HostAddress = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Initialize-Venv() {
    $hasPython = Test-Path ".venv\\Scripts\\python.exe"
    $hasCfg = Test-Path ".venv\\pyvenv.cfg"

    $venvPython = Join-Path (Get-Location) ".venv\\Scripts\\python.exe"
    $depsOk = $false
    if ($hasPython -and $hasCfg) {
        try {
            & $venvPython -c "import fastapi, uvicorn, openai" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $depsOk = $true
            }
        }
        catch {
            $depsOk = $false
        }
    }

    if ($hasPython -and $hasCfg -and $depsOk) {
        return
    }

    if (Test-Path ".venv") {
        Remove-Item -Recurse -Force ".venv"
    }

    # Use system site-packages to avoid dependency installs.
    # Use --without-pip to avoid ensurepip during venv creation.
    python -m venv .venv --system-site-packages --without-pip

    $venvPython = Join-Path (Get-Location) ".venv\\Scripts\\python.exe"
    try {
        & $venvPython -c "import fastapi, uvicorn, openai" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }
    catch {
        # Fall through to pip bootstrap below.
    }

    Write-Output "Venv created but deps not importable; bootstrapping pip and installing requirements..."
    & $venvPython -m ensurepip --upgrade
    & $venvPython -m pip install -r requirements.txt
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found on PATH. Install Python 3.10+ and ensure 'python' works."
}

Initialize-Venv

$pythonExe = Resolve-Path ".\\.venv\\Scripts\\python.exe"

Write-Output "Serving workbench at http://${HostAddress}:$Port/"
& $pythonExe -m uvicorn server:app --host $HostAddress --port $Port --log-level info
