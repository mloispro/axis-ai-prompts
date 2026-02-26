param(
    [switch]$InstallBrowsersOnly,
    [switch]$InstallBrowsers,
    [int]$StartPort = 8787,
    [int]$MaxPortTries = 20
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js not found on PATH. Install Node.js 18+ and ensure 'node' works."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found on PATH. Reinstall Node.js (includes npm)."
}

if (-not (Test-Path "node_modules")) {
    Write-Output "Installing Node dependencies..."
    npm install
}

function Test-PlaywrightBrowsersInstalled() {
    $roots = @()

    # If explicitly set, prefer it.
    if ($env:PLAYWRIGHT_BROWSERS_PATH -and $env:PLAYWRIGHT_BROWSERS_PATH -ne '0') {
        $roots += $env:PLAYWRIGHT_BROWSERS_PATH
    }

    # Default Windows location.
    if ($env:LOCALAPPDATA) {
        $roots += (Join-Path $env:LOCALAPPDATA 'ms-playwright')
    }
    if ($env:USERPROFILE) {
        $roots += (Join-Path $env:USERPROFILE 'AppData\\Local\\ms-playwright')
    }

    foreach ($r in $roots) {
        try {
            if (-not (Test-Path $r)) { continue }
            $dirs = Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue
            if ($dirs | Where-Object { $_.Name -match '^(chromium|firefox|webkit)-' }) {
                return $true
            }
        }
        catch {
            # Best-effort detection.
        }
    }

    return $false
}

$shouldInstall = $InstallBrowsersOnly -or $InstallBrowsers -or (-not (Test-PlaywrightBrowsersInstalled))
if ($shouldInstall) {
    Write-Output "Installing Playwright browsers..."
    npx playwright install
}
else {
    Write-Output "Playwright browsers already installed; skipping install."
}

if ($InstallBrowsersOnly) {
    exit 0
}

function Test-PortFree([int]$port) {
    # Reliable cross-shell check: attempt to bind the port.
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

$port = $StartPort
$tries = 0
while ($tries -lt $MaxPortTries -and -not (Test-PortFree $port)) {
    $port++
    $tries++
}
if ($tries -ge $MaxPortTries) {
    throw "Could not find a free/reusable port starting at $StartPort."
}

$env:WORKBENCH_PORT = "$port"
Write-Output "Using WORKBENCH_PORT=$port"

Write-Output "Running Playwright tests..."
npx playwright test
