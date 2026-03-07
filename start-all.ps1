param(
    [switch]$OpenDiagnostics,
    [ValidateSet("static", "dev")]
    [string]$FrontendMode = "dev",
    [int]$AiTimeoutSeconds = 30,
    [int]$ApiTimeoutSeconds = 30,
    [int]$FrontendTimeoutSeconds = 45
)

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

function Resolve-AiPython {
    param([string]$rootPath)

    $candidates = @(
        (Join-Path $rootPath "ai-engine-python\.venv312\Scripts\python.exe"),
        (Join-Path $rootPath "ai-engine-python\.venv\Scripts\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return "python"
}

function Invoke-AiPreflight {
    param([string]$rootPath)
    Write-Host "Running AI preflight checks..." -ForegroundColor Cyan
    Push-Location (Join-Path $rootPath "ai-engine-python")
    try {
        $venvPython = Resolve-AiPython -rootPath $rootPath
        & $venvPython "tools/check_runtime.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Python runtime/OCR backend check failed."
        }
        & $venvPython -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8-sig')) for p in pathlib.Path('app/pipelines/extract').glob('*.py')]; print('extract package syntax ok')"
        if ($LASTEXITCODE -ne 0) {
            throw "Python compile check failed."
        }
        & $venvPython "tools/run_regressions.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Regression suite check failed."
        }
        Write-Host "AI preflight checks passed." -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

function Invoke-ApiPreflight {
    param([string]$rootPath)
    Write-Host "Running API preflight checks..." -ForegroundColor Cyan
    Push-Location (Join-Path $rootPath "backend-dotnet\src\Api")
    try {
        $env:MSBuildEnableWorkloadResolver = "false"
        & dotnet msbuild "Api.csproj" /t:Restore /m:1 /nr:false /v:minimal
        if ($LASTEXITCODE -ne 0) {
            throw "API restore check failed."
        }
        & dotnet msbuild "Api.csproj" /t:Build /p:RestorePackages=false /m:1 /nr:false /v:minimal
        if ($LASTEXITCODE -ne 0) {
            throw "API build check failed."
        }
        Write-Host "API preflight checks passed." -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

$frontendPort = Get-FreePort

Write-Host "Cleaning stale listeners..." -ForegroundColor Cyan
Stop-PortListeners -port 8000
Stop-PortListeners -port 5000

Invoke-AiPreflight -rootPath $root
Invoke-ApiPreflight -rootPath $root

Write-Host "Starting IA Engine..." -ForegroundColor Cyan
$aiLog = Join-Path $logs "ai-engine.log"
$aiErr = Join-Path $logs "ai-engine.err.log"
$venvPython = Resolve-AiPython -rootPath $root
$ai = Start-Process powershell -PassThru -ArgumentList @(
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-Command',
    "Set-Location -LiteralPath '$root\ai-engine-python'; . '$root\\load-env.ps1'; & '$venvPython' -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
) -RedirectStandardOutput $aiLog -RedirectStandardError $aiErr

Write-Host "Starting Backend API..." -ForegroundColor Cyan
$apiLog = Join-Path $logs "backend-api.log"
$apiErr = Join-Path $logs "backend-api.err.log"
$apiScriptPath = Join-Path $root "start-api-quick.ps1"
$api = Start-Process powershell -PassThru -ArgumentList @(
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-Command',
    "& '$apiScriptPath' -NoBuild -Force"
) -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr

Write-Host "Starting Frontend (port $frontendPort)..." -ForegroundColor Cyan
$feLog = Join-Path $logs "frontend.log"
$feErr = Join-Path $logs "frontend.err.log"
$fe = $null
$frontendRuntimeMode = "none"
if ($FrontendMode -eq "dev") {
    $fe = Start-Process powershell -PassThru -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-Command',
        "Set-Location -LiteralPath '$root\frontend-angular\web'; npm start -- --port $frontendPort"
    ) -RedirectStandardOutput $feLog -RedirectStandardError $feErr
    $frontendRuntimeMode = "dev-server"
} else {
    $distPath = Join-Path $root "frontend-angular\web\dist\web\browser"
    if (Test-Path $distPath) {
        Write-Host "Using static frontend from dist." -ForegroundColor Yellow
        $fe = Start-Process powershell -PassThru -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-Command',
            "py -3 -m http.server $frontendPort --bind 127.0.0.1 --directory '$distPath'"
        ) -RedirectStandardOutput $feLog -RedirectStandardError $feErr
        $frontendRuntimeMode = "static-fallback"
    } else {
        Write-Host "Frontend skipped: static mode selected but dist build was not found." -ForegroundColor Yellow
    }
}

$pidFile = Join-Path $root "start-all.pids.json"
@{
    ai = $ai.Id
    api = $api.Id
    frontend = if ($fe) { $fe.Id } else { $null }
    frontendPort = $frontendPort
    frontendMode = $frontendRuntimeMode
} | ConvertTo-Json | Set-Content $pidFile

Write-Host "Waiting for services..." -ForegroundColor Cyan
$aiReady = Wait-ForUrl -url "http://localhost:8000/docs" -timeoutSeconds $AiTimeoutSeconds
$apiReady = Wait-ForUrl -url "http://localhost:5000/swagger" -timeoutSeconds $ApiTimeoutSeconds
$feReady = $false
$frontendExitedEarly = $false
if ($fe) {
    Start-Sleep -Milliseconds 800
    $frontendRunning = $null -ne (Get-Process -Id $fe.Id -ErrorAction SilentlyContinue)
    if ($frontendRunning) {
        $feReady = Wait-ForUrl -url "http://localhost:$frontendPort" -timeoutSeconds $FrontendTimeoutSeconds
    } else {
        $frontendExitedEarly = $true
        Write-Host "Frontend process exited immediately. Review logs/frontend.err.log." -ForegroundColor Yellow
    }
}

Write-Host "Frontend URL: http://localhost:$frontendPort" -ForegroundColor Green
# Keep startup focused on the frontend tab only.
if ($OpenDiagnostics) {
    Write-Host "OpenDiagnostics fue deshabilitado: se abre solo el frontend." -ForegroundColor Yellow
}
if ($feReady) { Start-Process "http://localhost:$frontendPort" }

if (-not $aiReady) { Write-Host "IA Engine no responde a tiempo." -ForegroundColor Yellow }
if (-not $apiReady) { Write-Host "Backend API no responde a tiempo." -ForegroundColor Yellow }
if ($fe -and -not $feReady -and -not $frontendExitedEarly) { Write-Host "Frontend no responde a tiempo." -ForegroundColor Yellow }

# Exit with non-zero code when any critical service failed to start
$exitCode = 0
if (-not $aiReady)  { $exitCode = 1 }
if (-not $apiReady) { $exitCode = 1 }
if ($fe -and -not $feReady) { $exitCode = 1 }
if ($exitCode -eq 0) {
    Write-Host "All services started successfully." -ForegroundColor Green
} else {
    Write-Host "One or more services failed health check - review logs/ for details." -ForegroundColor Red
}
exit $exitCode
