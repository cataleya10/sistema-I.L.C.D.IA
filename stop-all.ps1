$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "start-all.pids.json"

function Stop-ProcessTree {
    param([int]$Id)

    if (-not $Id -or $Id -eq $PID) {
        return
    }

    # taskkill /T stops children spawned by wrapper shells (Start-Process powershell ...).
    & taskkill /PID $Id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        try {
            Stop-Process -Id $Id -Force -ErrorAction Stop
        } catch {
            Write-Host "Process $Id not running." -ForegroundColor Yellow
        }
    }
}

function Stop-ByPort {
    param([int[]]$Ports)

    $listenerPids = @()
    foreach ($port in $Ports) {
        try {
            $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($listeners) {
                $listenerPids += ($listeners | Select-Object -ExpandProperty OwningProcess)
            }
        } catch {
            # Ignore platforms where Get-NetTCPConnection is not available.
        }
    }

    $listenerPids = $listenerPids | Where-Object { $_ -and $_ -ne $PID } | Sort-Object -Unique
    foreach ($listenerPid in $listenerPids) {
        Stop-ProcessTree -Id $listenerPid
    }
}

$ids = @()
if (Test-Path $pidFile) {
    $payload = Get-Content $pidFile -Raw | ConvertFrom-Json
    $ids += @($payload.ai, $payload.api, $payload.frontend)
}

$ids = $ids | Where-Object { $_ -ne $null } | Sort-Object -Unique
foreach ($id in $ids) {
    Stop-ProcessTree -Id $id
}

# Fallback cleanup in case PID file is stale but known service ports are still occupied.
Stop-ByPort -Ports @(4200, 5000, 8000)

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped." -ForegroundColor Green
