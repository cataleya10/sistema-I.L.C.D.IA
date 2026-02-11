$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Get-FreePort {
    param([int]$start = 4200, [int]$end = 4299)
    for ($port = $start; $port -le $end; $port++) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
            $listener.Start()
            $listener.Stop()
            return $port
        } catch {
            # port in use, try next
        }
    }
    throw "No free port available between $start and $end."
}

function Wait-ForUrl {
    param(
        [string]$url,
        [int]$timeoutSeconds = 60
    )
    $start = Get-Date
    while ((Get-Date) -lt $start.AddSeconds($timeoutSeconds)) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Stop-PortListeners {
    param([int]$port)
    try {
        $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if (-not $listeners) { return }
        $processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $processIds) {
            if ($processId -and $processId -ne $PID) {
                try { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue } catch {}
            }
        }
        Start-Sleep -Milliseconds 600
    } catch {
        # ignore cleanup failures
    }
}

function Invoke-AiPreflight {
    param([string]$rootPath)
    Write-Host "Running AI preflight checks..." -ForegroundColor Cyan
    Push-Location (Join-Path $rootPath "ai-engine-python")
    try {
        & py -3 -m py_compile "app/pipelines/extract.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Python compile check failed."
        }
        & py -3 "tools/run_regressions.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Regression suite check failed."
        }
        Write-Host "AI preflight checks passed." -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

$frontendPort = Get-FreePort

Write-Host "Cleaning stale listeners..." -ForegroundColor Cyan
Stop-PortListeners -port 8000
Stop-PortListeners -port 5000

Invoke-AiPreflight -rootPath $root

Write-Host "Starting IA Engine..." -ForegroundColor Cyan
$aiLog = Join-Path $logs "ai-engine.log"
$aiErr = Join-Path $logs "ai-engine.err.log"
$ai = Start-Process powershell -PassThru -ArgumentList @(
    '-NoExit',
    '-Command',
    "Set-Location -LiteralPath '$root\ai-engine-python'; . '$root\\load-env.ps1'; uvicorn app.main:app --host 0.0.0.0 --port 8000"
) -RedirectStandardOutput $aiLog -RedirectStandardError $aiErr

Write-Host "Starting Backend API..." -ForegroundColor Cyan
$apiLog = Join-Path $logs "backend-api.log"
$apiErr = Join-Path $logs "backend-api.err.log"
$api = Start-Process powershell -PassThru -ArgumentList @(
    '-NoExit',
    '-Command',
    "Set-Location -LiteralPath '$root\backend-dotnet\src\Api'; `$env:ASPNETCORE_ENVIRONMENT='Development'; . '$root\\load-env.ps1'; dotnet run --launch-profile http"
) -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr

Write-Host "Starting Frontend (port $frontendPort)..." -ForegroundColor Cyan
$feLog = Join-Path $logs "frontend.log"
$feErr = Join-Path $logs "frontend.err.log"
$fe = Start-Process powershell -PassThru -ArgumentList @('-NoExit', '-Command', "Set-Location -LiteralPath '$root\frontend-angular\web'; npm start -- --port $frontendPort") -RedirectStandardOutput $feLog -RedirectStandardError $feErr

$pidFile = Join-Path $root "start-all.pids.json"
@{
    ai = $ai.Id
    api = $api.Id
    frontend = $fe.Id
    frontendPort = $frontendPort
} | ConvertTo-Json | Set-Content $pidFile

Write-Host "Waiting for services..." -ForegroundColor Cyan
$aiReady = Wait-ForUrl -url "http://localhost:8000/docs" -timeoutSeconds 90
$apiReady = Wait-ForUrl -url "http://localhost:5000/swagger" -timeoutSeconds 90
$feReady = Wait-ForUrl -url "http://localhost:$frontendPort" -timeoutSeconds 120

Write-Host "Frontend URL: http://localhost:$frontendPort" -ForegroundColor Green
if ($aiReady) { Start-Process "http://localhost:8000/docs" }
if ($apiReady) { Start-Process "http://localhost:5000/swagger" }
if ($feReady) { Start-Process "http://localhost:$frontendPort" }

if (-not $aiReady) { Write-Host "IA Engine no responde a tiempo." -ForegroundColor Yellow }
if (-not $apiReady) { Write-Host "Backend API no responde a tiempo." -ForegroundColor Yellow }
if (-not $feReady) { Write-Host "Frontend no responde a tiempo." -ForegroundColor Yellow }
