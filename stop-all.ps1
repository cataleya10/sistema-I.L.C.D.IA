$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "start-all.pids.json"
if (-not (Test-Path $pidFile)) {
    Write-Host "No pid file found. Nothing to stop." -ForegroundColor Yellow
    return
}

$payload = Get-Content $pidFile -Raw | ConvertFrom-Json
$ids = @($payload.ai, $payload.api, $payload.frontend) | Where-Object { $_ -ne $null }
foreach ($id in $ids) {
    try {
        Stop-Process -Id $id -Force -ErrorAction Stop
    } catch {
        Write-Host "Process $id not running." -ForegroundColor Yellow
    }
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped." -ForegroundColor Green
