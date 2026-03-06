[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Root output directory. Defaults to tools/workbench-web/out
    [string]$OutDir = '',

    # Keep the most recent N engine run directories (by name, which is a UTC timestamp slug).
    [int]$KeepLast = 10,

    # Also keep anything written within the last N days (safety net).
    [int]$KeepDays = 0,

    # Optional: prune trace files under out/traces older than KeepDays.
    [switch]$PruneTraces
)

$ErrorActionPreference = 'Stop'

function Write-Info([string]$msg) { Write-Host "[prune-out] $msg" }

if (-not $OutDir) {
    $scriptPath = $MyInvocation.MyCommand.Path
    $scriptDir = Split-Path -Parent $scriptPath
    $OutDir = Join-Path (Split-Path -Parent $scriptDir) 'out'
}

$resolvedOutDir = $null
try {
    $resolvedOutDir = (Resolve-Path -Path $OutDir -ErrorAction Stop).Path
}
catch {
    Write-Info "OutDir not found: $OutDir"
    exit 0
}

$specialNames = @('audit', 'launcher', 'logs')
$cutoff = (Get-Date).AddDays(-1 * [Math]::Abs($KeepDays))

Write-Info "OutDir=$resolvedOutDir"
Write-Info "Policy: keep last $KeepLast runs AND keep anything newer than $($cutoff.ToString('s'))"

$allDirs = Get-ChildItem -Path $resolvedOutDir -Directory -ErrorAction Stop

# Engine run dirs look like: 20260306_171628 (UTC timestamp slug) and contain run.json.
$runDirs = $allDirs |
Where-Object { $_.Name -match '^\d{8}_\d{6}$' } |
Where-Object { Test-Path (Join-Path $_.FullName 'run.json') }

# Safety: never touch special folders.
$runDirs = $runDirs | Where-Object { $specialNames -notcontains $_.Name }

if (-not $runDirs -or $runDirs.Count -eq 0) {
    Write-Info "No run directories found to prune."
}
else {
    $sorted = $runDirs | Sort-Object Name -Descending
    $keepByCount = @()
    if ($KeepLast -gt 0) {
        $keepByCount = $sorted | Select-Object -First $KeepLast
    }

    $keepSet = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($d in $keepByCount) {
        [void]$keepSet.Add($d.FullName)
    }
    foreach ($d in $runDirs) {
        if ($d.LastWriteTime -ge $cutoff) {
            [void]$keepSet.Add($d.FullName)
        }
    }

    $toDelete = $sorted | Where-Object { -not $keepSet.Contains($_.FullName) }

    Write-Info "Found runs: $($runDirs.Count); keeping: $($keepSet.Count); deleting: $($toDelete.Count)"

    foreach ($d in $toDelete) {
        $target = $d.FullName
        if ($PSCmdlet.ShouldProcess($target, 'Remove old run output directory')) {
            try {
                Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
            }
            catch {
                Write-Info "WARN: failed to delete $target ($($_.Exception.Message))"
            }
        }
    }
}

if ($PruneTraces) {
    $tracesDir = Join-Path $resolvedOutDir 'traces'
    if (Test-Path $tracesDir) {
        Write-Info "Pruning traces older than $($cutoff.ToString('s')) in $tracesDir"
        try {
            $oldTraceFiles = Get-ChildItem -Path $tracesDir -File -Recurse -ErrorAction Stop |
            Where-Object { $_.LastWriteTime -lt $cutoff }
            foreach ($f in $oldTraceFiles) {
                if ($PSCmdlet.ShouldProcess($f.FullName, 'Remove old trace file')) {
                    try {
                        Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop
                    }
                    catch {
                        Write-Info "WARN: failed to delete trace file $($f.FullName) ($($_.Exception.Message))"
                    }
                }
            }
        }
        catch {
            Write-Info "WARN: trace pruning failed ($($_.Exception.Message))"
        }
    }
    else {
        Write-Info "No traces directory present; skipping trace prune."
    }
}

Write-Info "Done. Tip: run with -WhatIf first to preview deletions."
