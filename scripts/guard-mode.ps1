param(
    [string]$ApiBase = "http://localhost:5000",
    [string]$AiBase = "http://localhost:8000",
    [string]$FrontendBase = "http://localhost:4200",
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Secret,
    [int]$MaxRecoveryAttempts = 1
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Test-Url {
    param(
        [string]$Url,
        [int]$TimeoutSec = 5
    )
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return $resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-Url {
    param(
        [string]$Url,
        [int]$TimeoutSec = 90
    )
    $start = Get-Date
    while ((Get-Date) -lt $start.AddSeconds($TimeoutSec)) {
        if (Test-Url -Url $Url -TimeoutSec 5) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-Stack {
    Write-Host "==> Iniciando stack (IA + API + Web)..." -ForegroundColor Cyan
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "start-all.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "start-all.ps1 fallo."
    }
}

function Stop-Stack {
    Write-Host "==> Reinicio de recuperacion (stop-all/start-all)..." -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root "stop-all.ps1")
    Start-Sleep -Seconds 1
    Start-Stack
}

function Assert-StackReady {
    Write-Host "==> Validando disponibilidad de servicios..." -ForegroundColor Cyan
    if (-not (Wait-Url -Url "$ApiBase/health" -TimeoutSec 120)) {
        throw "API no responde en $ApiBase/health."
    }
    if (-not (Wait-Url -Url "$AiBase/docs" -TimeoutSec 120)) {
        throw "Motor IA no responde en $AiBase/docs."
    }
    if (-not (Wait-Url -Url $FrontendBase -TimeoutSec 150)) {
        throw "Frontend no responde en $FrontendBase."
    }
    Write-Host "[OK] Servicios disponibles." -ForegroundColor Green
}

function Run-Checks {
    Write-Host "==> Ejecutando smoke..." -ForegroundColor Cyan
    & powershell -File (Join-Path $root "scripts\smoke.ps1") -ApiBase $ApiBase -AiBase $AiBase -Username $Username -Secret $Secret
    if ($LASTEXITCODE -ne 0) {
        throw "smoke.ps1 reporto error."
    }

    Write-Host "==> Ejecutando check de acciones UI/API..." -ForegroundColor Cyan
    & powershell -File (Join-Path $root "scripts\check-ui-actions.ps1") -ApiBase $ApiBase -Username $Username -Secret $Secret
    if ($LASTEXITCODE -ne 0) {
        throw "check-ui-actions.ps1 reporto error."
    }
}

try {
    $apiUp = Test-Url -Url "$ApiBase/health"
    $aiUp = Test-Url -Url "$AiBase/docs"
    $webUp = Test-Url -Url $FrontendBase

    if (-not ($apiUp -and $aiUp -and $webUp)) {
        Start-Stack
    }

    Assert-StackReady

    $attempt = 0
    while ($true) {
        try {
            Run-Checks
            break
        } catch {
            if ($attempt -ge $MaxRecoveryAttempts) {
                throw
            }
            $attempt += 1
            Write-Host "[WARN] Fallo detectado: $($_.Exception.Message)" -ForegroundColor Yellow
            Stop-Stack
            Assert-StackReady
        }
    }

    Write-Host ""
    Write-Host "[OK] Modo protegido: sistema estable y validado." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
