param(
    [int]$StartPort = 8787,
    [int]$MaxPortTries = 20,
    [int]$StartupTimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

Write-Output "[run.ps1] starting..."

try {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location $root

    function Test-PortFree([int]$port) {
        # Reliable check: attempt to bind the port.
        # If another process is listening, Start() will throw.
        $listener = $null
        try {
            $ip = [System.Net.IPAddress]::Parse('127.0.0.1')
            $listener = [System.Net.Sockets.TcpListener]::new($ip, $port)
            $listener.Start()
            return $true
        }
        catch {
            return $false
        }
        finally {
            try { if ($listener) { $listener.Stop() } } catch {}
        }
    }

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

    function Wait-HttpOk([string]$url, [int]$timeoutSeconds) {
        $deadline = (Get-Date).AddSeconds($timeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            try {
                $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url
                if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                    return $true
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        return $false
    }

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python not found on PATH. Install Python 3.10+ and ensure 'python' works in Command Prompt."
    }

    Initialize-Venv

    $port = $StartPort
    $tries = 0
    while ($tries -lt $MaxPortTries -and -not (Test-PortFree $port)) {
        $alreadyUp = Wait-HttpOk -url ("http://127.0.0.1:$port/api/apps") -timeoutSeconds 1
        if ($alreadyUp) {
            $url = "http://127.0.0.1:$port/"
            Write-Output "Workbench already running at $url"
            Start-Process $url
            exit 0
        }

        $port++
        $tries++
    }
    if ($tries -ge $MaxPortTries) {
        throw "Could not find a free port starting at $StartPort."
    }

    $logDir = Join-Path $root "out\\launcher"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFileOut = Join-Path $logDir ("uvicorn-{0}.out.log" -f $port)
    $logFileErr = Join-Path $logDir ("uvicorn-{0}.err.log" -f $port)
    New-Item -ItemType File -Force -Path $logFileOut | Out-Null
    New-Item -ItemType File -Force -Path $logFileErr | Out-Null

    $url = "http://127.0.0.1:$port/"
    Write-Output "Starting ai-prompts workbench at $url"
    Write-Output "Logs: $logFileOut"
    Write-Output "Errors: $logFileErr"

    $pythonExe = Resolve-Path ".\\.venv\\Scripts\\python.exe"
    $uvicornArgs = @(
        '-m', 'uvicorn', 'server:app',
        '--host', '127.0.0.1',
        '--port', "$port",
        '--log-level', 'info'
    )

    $proc = Start-Process -FilePath $pythonExe -WorkingDirectory $root -ArgumentList $uvicornArgs -RedirectStandardOutput $logFileOut -RedirectStandardError $logFileErr -PassThru

    $ok = Wait-HttpOk -url ("http://127.0.0.1:$port/api/apps") -timeoutSeconds $StartupTimeoutSeconds
    if (-not $ok) {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        throw "Server did not become ready within ${StartupTimeoutSeconds}s. See logs: $logFileOut and $logFileErr"
    }

    Start-Process $url
    Write-Output "Server PID: $($proc.Id)"
    exit 0
}
catch {
    Write-Output "Launcher error: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) { Write-Output $_.ScriptStackTrace }
    exit 1
}
