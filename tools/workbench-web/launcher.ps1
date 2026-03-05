param(
    [string]$Mode = 'run',

    [int]$StartPort = 8787,
    [int]$Port = 8787,
    [string]$HostAddress = '127.0.0.1',

    [switch]$NoOpen,
    [switch]$RestartOnPortInUse,
    [switch]$Restart,
    [switch]$Detached,
    [switch]$NoPortDrift,
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

function Start-OpenWhenReadyJob([string]$apiUrl, [string]$homeUrl, [int]$timeoutSeconds) {
    if ($NoOpen) {
        return
    }

    # Avoid racing the browser open before the server is actually reachable.
    # Run as a background job so foreground uvicorn logs remain in the terminal.
    try {
        Start-Job -ScriptBlock {
            param($ApiUrl, $HomeUrl, $TimeoutSeconds)

            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            while ((Get-Date) -lt $deadline) {
                try {
                    $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $ApiUrl
                    if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                        Start-Process $HomeUrl | Out-Null
                        return
                    }
                }
                catch {
                    Start-Sleep -Milliseconds 250
                }
            }
        } -ArgumentList $apiUrl, $homeUrl, $timeoutSeconds | Out-Null
        return
    }
    catch {
        # Some environments disable PowerShell jobs. Fall back to a detached poller process
        # instead of opening immediately (which can cause ERR_CONNECTION_REFUSED).
        try {
            $cmd = @"
\$ApiUrl = '$apiUrl'
\$HomeUrl = '$homeUrl'
\$TimeoutSeconds = $timeoutSeconds
\$deadline = (Get-Date).AddSeconds(\$TimeoutSeconds)
while ((Get-Date) -lt \$deadline) {
  try {
    \$resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 \$ApiUrl
    if (\$resp.StatusCode -ge 200 -and \$resp.StatusCode -lt 500) {
      Start-Process \$HomeUrl | Out-Null
      exit 0
    }
  } catch {
    Start-Sleep -Milliseconds 250
  }
}
"@
            Start-Process -WindowStyle Hidden -FilePath powershell -ArgumentList @(
                '-NoProfile',
                '-ExecutionPolicy', 'Bypass',
                '-Command', $cmd
            ) | Out-Null
        }
        catch {
            # Last resort: do nothing.
        }
    }
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
    if ($processId -le 0) { return $false }
    # Try Stop-Process first.
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Output "Stopped PID $processId"
        return $true
    }
    catch { }
    # Fallback: taskkill (works in more contexts than Stop-Process).
    try {
        $result = & taskkill /F /T /PID $processId 2>&1
        $null = $result
        if ($LASTEXITCODE -eq 0) {
            Write-Output "Stopped PID $processId (via taskkill)"
            return $true
        }
    }
    catch { }
    return $false
}

function Start-Detached([int]$fixedPort, [bool]$useReload) {
    Initialize-Venv

    if ($Restart) {
        Write-Output "[launcher] restart requested; stopping previous server (best-effort)..."
        try { Stop-FromLastJson | Out-Null } catch { }
        Start-Sleep -Milliseconds 250
    }

    $openUrl = "http://${HostAddress}:$fixedPort/"
    $apiUrl = "http://${HostAddress}:$fixedPort/api/apps"

    # If the port is already in use, dev/serve should be able to recover.
    if (-not (Test-PortFree -portToTest $fixedPort)) {
        $alreadyUp = Wait-HttpOk -url $apiUrl -timeoutSeconds 1
        if ($alreadyUp -and -not $RestartOnPortInUse -and -not $Restart) {
            Write-Output "Workbench already running at $openUrl"
            Start-OpenWhenReadyJob -apiUrl $apiUrl -homeUrl $openUrl -timeoutSeconds $OpenTimeoutSeconds
            return
        }

        Write-Output "Port $fixedPort is in use; stopping existing listener..."
        try { Stop-ByPort -portToStop $fixedPort | Out-Null } catch {}
        Start-Sleep -Milliseconds 300

        # If we couldn't stop it, auto-find the next free port rather than failing.
        # The UI shows the exact origin/port in the top bar to avoid confusion.
        if (-not (Test-PortFree -portToTest $fixedPort)) {
            if ($NoPortDrift) {
                throw "Port $fixedPort is in use and could not be stopped. (Fixed-port mode: refusing to drift.)"
            }
            $originalPort = $fixedPort
            $tries = 0
            while ($tries -lt $MaxPortTries -and -not (Test-PortFree -portToTest $fixedPort)) {
                $fixedPort++
                $tries++
            }
            if ($tries -ge $MaxPortTries) {
                throw "Could not find a free port near $originalPort. Kill stale processes manually."
            }
            Write-Output "WARNING: Port $originalPort is stuck; using port $fixedPort instead. Use the URL printed below (and note the port)."
            $openUrl = "http://${HostAddress}:$fixedPort/"
            $apiUrl = "http://${HostAddress}:$fixedPort/api/apps"
        }
    }

    $logDir = Join-Path $root "out\\launcher"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $modeLabel = if ($useReload) { 'dev' } else { 'serve' }
    $logFileOut = Join-Path $logDir ("uvicorn-{0}-{1}.out.log" -f $modeLabel, $fixedPort)
    $logFileErr = Join-Path $logDir ("uvicorn-{0}-{1}.err.log" -f $modeLabel, $fixedPort)
    New-Item -ItemType File -Force -Path $logFileOut | Out-Null
    New-Item -ItemType File -Force -Path $logFileErr | Out-Null

    Write-Output "Starting workbench at $openUrl"
    Write-Output "Logs: $logFileOut"
    Write-Output "Errors: $logFileErr"

    $pythonExe = Resolve-Path ".\\.venv\\Scripts\\python.exe"
    $argList = @(
        '-m', 'uvicorn', 'server:app'
    )
    if ($useReload) {
        $argList += '--reload'
    }
    $argList += @(
        '--host', $HostAddress,
        '--port', "$fixedPort",
        '--log-level', 'info'
    )

    $proc = Start-Process -FilePath $pythonExe -WorkingDirectory $root -ArgumentList $argList -RedirectStandardOutput $logFileOut -RedirectStandardError $logFileErr -PassThru

    $ok = Wait-HttpOk -url $apiUrl -timeoutSeconds $StartupTimeoutSeconds
    if (-not $ok) {
        try { Stop-ByProcessId -processId $proc.Id | Out-Null } catch {}
        throw "Server did not become ready within ${StartupTimeoutSeconds}s. See logs: $logFileOut and $logFileErr"
    }

    try {
        $startedAt = (Get-Date).ToUniversalTime().ToString('o')
        $lastFile = Join-Path $logDir "last.json"
        $obj = @{
            pid       = $proc.Id
            port      = $fixedPort
            url       = $openUrl
            startedAt = $startedAt
            mode      = $modeLabel
        }
        ($obj | ConvertTo-Json -Depth 4) | Set-Content -Encoding UTF8 -Path $lastFile
    }
    catch {
        # Non-fatal.
    }

    if (-not $NoOpen) {
        Start-Process $openUrl | Out-Null
    }

    Write-Output "Server PID: $($proc.Id)"
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

function Get-ServerPidFromApi([string]$baseUrl) {
    if (-not $baseUrl) { return 0 }
    $infoUrl = $baseUrl.TrimEnd('/') + '/api/info'
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 $infoUrl
        if (-not $resp -or -not $resp.Content) { return 0 }
        $obj = $resp.Content | ConvertFrom-Json
        if ($obj -and $obj.pid) {
            return [int]($obj.pid)
        }
    }
    catch {
        return 0
    }
    return 0
}

function Stop-ByPort([int]$portToStop) {
    # Prefer asking the running server for its own PID (most reliable in environments
    # where netstat/Get-NetTCPConnection report a non-existent OwningProcess PID).
    try {
        $apiPid = Get-ServerPidFromApi -baseUrl ("http://${HostAddress}:$portToStop")
        if ($apiPid -gt 0) {
            $killed = Stop-ByProcessId -processId $apiPid
            if ($killed) { return $true }
        }
    }
    catch { }

    $processId = Get-ListeningProcessIdForPort -portToFind $portToStop
    if ($processId -gt 0) {
        $killed = Stop-ByProcessId -processId $processId
        if ($killed) { return $true }
    }
    # Last resort: if a WSL distro is running it may own the port via NAT forwarding.
    # Shutting down WSL releases all forwarded ports cleanly.
    $wslRunning = $false
    try {
        $wslOut = & wsl --list --running 2>&1
        $wslRunning = ($LASTEXITCODE -eq 0) -and ($wslOut -match '\S')
    }
    catch { }
    if ($wslRunning) {
        Write-Output "Port $portToStop appears WSL-forwarded. Running wsl --shutdown to release it..."
        try { & wsl --shutdown 2>&1 | Out-Null } catch { }
        Start-Sleep -Milliseconds 800
        if (Test-PortFree -portToTest $portToStop) {
            Write-Output "Port $portToStop released after wsl --shutdown."
            return $true
        }
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
        $urlFromFile = ""
        try { if ($obj.url) { $urlFromFile = [string]($obj.url) } } catch { }

        # Most reliable: stop the root process we started (kills children via /T).
        if ($processId -gt 0 -and (Stop-ByProcessId -processId $processId)) {
            return $true
        }

        # Next best: ask the currently running server for its PID.
        if ($urlFromFile) {
            $apiPid = Get-ServerPidFromApi -baseUrl $urlFromFile
            if ($apiPid -gt 0 -and (Stop-ByProcessId -processId $apiPid)) {
                return $true
            }
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
    $apiUrl = "http://${HostAddress}:$fixedPort/api/apps"

    # If the port is already in use, dev/serve should be able to recover.
    if (-not (Test-PortFree -portToTest $fixedPort)) {
        $alreadyUp = Wait-HttpOk -url $apiUrl -timeoutSeconds 1
        if ($alreadyUp -and -not $RestartOnPortInUse) {
            Write-Output "Workbench already running at $openUrl"
            Start-OpenWhenReadyJob -apiUrl $apiUrl -homeUrl $openUrl -timeoutSeconds $OpenTimeoutSeconds
            return
        }

        Write-Output "Port $fixedPort is in use; stopping existing listener..."
        try { Stop-ByPort -portToStop $fixedPort | Out-Null } catch {}
        Start-Sleep -Milliseconds 300

        # If we couldn't stop it, auto-find the next free port rather than failing.
        # The UI shows the exact origin/port in the top bar to avoid confusion.
        if (-not (Test-PortFree -portToTest $fixedPort)) {
            if ($NoPortDrift) {
                throw "Port $fixedPort is in use and could not be stopped. (Fixed-port mode: refusing to drift.)"
            }
            $originalPort = $fixedPort
            $tries = 0
            while ($tries -lt $MaxPortTries -and -not (Test-PortFree -portToTest $fixedPort)) {
                $fixedPort++
                $tries++
            }
            if ($tries -ge $MaxPortTries) {
                throw "Could not find a free port near $originalPort. Kill stale processes manually."
            }
            Write-Output "WARNING: Port $originalPort is stuck; using port $fixedPort instead. Use the URL printed below (and note the port)."
            $openUrl = "http://${HostAddress}:$fixedPort/"
            $apiUrl = "http://${HostAddress}:$fixedPort/api/apps"
        }
    }

    Write-Output "Starting workbench at $openUrl"
    Start-OpenWhenReadyJob -apiUrl $apiUrl -homeUrl $openUrl -timeoutSeconds $OpenTimeoutSeconds

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
        $apiUrl = "http://${HostAddress}:$Port/api/apps"
        if (Wait-HttpOk -url $apiUrl -timeoutSeconds 1) {
            Write-Output "Workbench is responding at http://${HostAddress}:$Port/ but could not be stopped by PID/port. Close the existing terminal/process holding the port or run with enough permissions."
            exit 1
        }
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
        if ($Detached) {
            Start-Detached -fixedPort $Port -useReload $true
        }
        else {
            Start-Foreground -fixedPort $Port -useReload $true
        }
        exit 0
    }
    'serve' {
        if ($Detached) {
            Start-Detached -fixedPort $Port -useReload $false
        }
        else {
            Start-Foreground -fixedPort $Port -useReload $false
        }
        exit 0
    }
    default {
        Start-Background -startPort $StartPort
        exit 0
    }
}
