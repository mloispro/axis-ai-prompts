param(
    [int]$Port = 8787,
    [string]$HostAddress = '127.0.0.1',
    [switch]$NoOpen,
    [int]$OpenTimeoutSeconds = 15
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
        Write-Output "Existing venv is missing deps or is incomplete. Recreating it..."
        Remove-Item -Recurse -Force ".venv"
    }
    else {
        Write-Output "Missing venv. Creating it now..."
    }

    # Prefer system site-packages for reliability (avoids network installs).
    # Use --without-pip to skip ensurepip during venv creation (can be slow/flaky).
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
$openUrl = "http://${HostAddress}:$Port/"
$readyUrl = "http://${HostAddress}:$Port/api/apps"

Write-Output "Starting workbench at $openUrl"

if (-not $NoOpen) {
    Start-Job -ArgumentList $openUrl, $readyUrl, $OpenTimeoutSeconds -ScriptBlock {
        param($url, $healthUrl, $timeoutSeconds)

        $deadline = (Get-Date).AddSeconds($timeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            try {
                $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $healthUrl
                if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                    Start-Process $url
                    return
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }

        # Best-effort open even if health never came up.
        try { Start-Process $url } catch {}
    } | Out-Null
}

# Run in the foreground so VS Code Stop ends the server.
& $pythonExe -m uvicorn server:app --host $HostAddress --port $Port --log-level info
