param(
    [string]$Mode = 'run',

    [int]$StartPort = 8787,
    [int]$Port = 8787,
    [string]$HostAddress = '127.0.0.1',

    [switch]$NoOpen,
    [int]$OpenTimeoutSeconds = 15,

    [int]$MaxPortTries = 20,
    [int]$StartupTimeoutSeconds = 15
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

function Test-PortFree([int]$portToTest) {
    $listener = $null
    try {
        $ip = [System.Net.IPAddress]::Parse('127.0.0.1')
        $listener = [System.Net.Sockets.TcpListener]::new($ip, $portToTest)
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

function Stop-ByProcessId([int]$processId) {
    try {
        $p = Get-Process -Id $processId -ErrorAction Stop
        Stop-Process -Id $processId -Force
        Write-Output "Stopped PID $processId ($($p.ProcessName))"
        return $true
    }
    catch {
        return $false
    }
}

function Get-ListeningProcessIdForPort([int]$portToFind) {
    if ($portToFind -le 0) { return 0 }

    try {
        $conn = Get-NetTCPConnection -LocalPort $portToFind -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($conn -and $conn.OwningProcess) {
            return [int]$conn.OwningProcess
        }
    }
    catch {
        # Fall back to netstat parsing below.
    }

    try {
        $lines = & netstat -ano | Select-String -Pattern (":$portToFind\s")
        foreach ($line in $lines) {
            $text = ($line.ToString()).Trim()
            if ($text -match "\sLISTENING\s+(\d+)$") {
                return [int]$Matches[1]
            }
        }
    }
    catch {
        # ignore
    }

    return 0
}

function Stop-ByPort([int]$portToStop) {
    $processId = Get-ListeningProcessIdForPort -portToFind $portToStop
    if ($processId -gt 0) {
        return Stop-ByProcessId -processId $processId
    }
    return $false
}

function Stop-FromLastJson() {
    $logDir = Join-Path $root "out\\launcher"
    $lastFile = Join-Path $logDir "last.json"

    if (-not (Test-Path $lastFile)) {
        return $false
    }

    try {
        $obj = Get-Content -Raw -Path $lastFile | ConvertFrom-Json
        $processId = [int]($obj.pid)
        $portFromFile = [int]($obj.port)

        if ($processId -gt 0 -and (Stop-ByProcessId -processId $processId)) {
            return $true
        }

        if ($portFromFile -gt 0 -and (Stop-ByPort -portToStop $portFromFile)) {
            return $true
        }
    }
    catch {
        return $false
    }

    return $false
}

function Start-Background([int]$startPort) {
    Initialize-Venv

    $portChosen = $startPort
    $tries = 0
    while ($tries -lt $MaxPortTries -and -not (Test-PortFree -portToTest $portChosen)) {
        $alreadyUp = Wait-HttpOk -url ("http://127.0.0.1:$portChosen/api/apps") -timeoutSeconds 1
        if ($alreadyUp) {
            $url = "http://127.0.0.1:$portChosen/"
            Write-Output "Workbench already running at $url"
            if (-not $NoOpen) { Start-Process $url }
            return
        }

        $portChosen++
        $tries++
    }

    if ($tries -ge $MaxPortTries) {
        throw "Could not find a free port starting at $startPort."
    }

    $logDir = Join-Path $root "out\\launcher"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFileOut = Join-Path $logDir ("uvicorn-{0}.out.log" -f $portChosen)
    $logFileErr = Join-Path $logDir ("uvicorn-{0}.err.log" -f $portChosen)
    New-Item -ItemType File -Force -Path $logFileOut | Out-Null
    New-Item -ItemType File -Force -Path $logFileErr | Out-Null
    $lastFile = Join-Path $logDir "last.json"

    $url = "http://127.0.0.1:$portChosen/"
    Write-Output "Starting ai-prompts workbench at $url"
    Write-Output "Logs: $logFileOut"
    Write-Output "Errors: $logFileErr"

    $pythonExe = Resolve-Path ".\\.venv\\Scripts\\python.exe"
    $proc = Start-Process -FilePath $pythonExe -WorkingDirectory $root -ArgumentList @(
        '-m', 'uvicorn', 'server:app',
        '--host', '127.0.0.1',
        '--port', "$portChosen",
        '--log-level', 'info'
    ) -RedirectStandardOutput $logFileOut -RedirectStandardError $logFileErr -PassThru

    $ok = Wait-HttpOk -url ("http://127.0.0.1:$portChosen/api/apps") -timeoutSeconds $StartupTimeoutSeconds
    if (-not $ok) {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        throw "Server did not become ready within ${StartupTimeoutSeconds}s. See logs: $logFileOut and $logFileErr"
    }

    if (-not $NoOpen) { Start-Process $url }
    Write-Output "Server PID: $($proc.Id)"

    try {
        $obj = @{
            pid       = $proc.Id
            port      = $portChosen
            url       = $url
            startedAt = (Get-Date).ToUniversalTime().ToString('o')
        }
        ($obj | ConvertTo-Json -Depth 4) | Set-Content -Encoding UTF8 -Path $lastFile
    }
    catch {
        # Non-fatal.
    }
}

function Start-Foreground([int]$fixedPort, [bool]$useReload) {
    Initialize-Venv

    $pythonExe = Resolve-Path ".\\.venv\\Scripts\\python.exe"
    $openUrl = "http://${HostAddress}:$fixedPort/"

    Write-Output "Starting workbench at $openUrl"
    if (-not $NoOpen) { try { Start-Process $openUrl } catch {} }

    if ($useReload) {
        & $pythonExe -m uvicorn server:app --reload --host $HostAddress --port $fixedPort --log-level info
    }
    else {
        & $pythonExe -m uvicorn server:app --host $HostAddress --port $fixedPort --log-level info
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found on PATH. Install Python 3.10+ and ensure 'python' works."
}

switch ($Mode) {
    'stop' {
        if (Stop-FromLastJson) { exit 0 }
        if (Stop-ByPort -portToStop $Port) { exit 0 }
        Write-Output "Nothing to stop."
        exit 0
    }
    'restart' {
        Write-Output "[launcher] stopping existing server (best-effort)..."
        try { Stop-FromLastJson | Out-Null } catch {}
        try { Stop-ByPort -portToStop $StartPort | Out-Null } catch {}
        Write-Output "[launcher] starting..."
        Start-Background -startPort $StartPort
        exit 0
    }
    'dev' {
        Start-Foreground -fixedPort $Port -useReload $true
        exit 0
    }
    'serve' {
        Start-Foreground -fixedPort $Port -useReload $false
        exit 0
    }
    default {
        Start-Background -startPort $StartPort
        exit 0
    }
}
