param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $root "start-all.ps1"
$stopScript = Join-Path $root "stop-all.ps1"
$pidFile = Join-Path $root "start-all.pids.json"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "No se encontro el comando requerido: $Name"
    }
}

function Show-Status {
    if (-not (Test-Path $pidFile)) {
        Write-Host "Estado: detenido (no existe start-all.pids.json)" -ForegroundColor Yellow
        return
    }

    $payload = Get-Content $pidFile -Raw | ConvertFrom-Json
    $targets = @(
        @{ Name = "AI"; Id = $payload.ai; Port = 8000 },
        @{ Name = "API"; Id = $payload.api; Port = 5000 },
        @{ Name = "Frontend"; Id = $payload.frontend; Port = [int]$payload.frontendPort }
    )

    foreach ($target in $targets) {
        $running = $false
        if ($target.Id) {
            $running = $null -ne (Get-Process -Id $target.Id -ErrorAction SilentlyContinue)
        }
        $state = if ($running) { "RUNNING" } else { "DOWN" }
        Write-Host ("{0,-10} PID={1,-8} PORT={2,-5} {3}" -f $target.Name, $target.Id, $target.Port, $state)
    }
}

if (-not (Test-Path $startScript)) {
    throw "No se encontro start-all.ps1 en $root"
}
if (-not (Test-Path $stopScript)) {
    throw "No se encontro stop-all.ps1 en $root"
}

switch ($Action) {
    "start" {
        Require-Command -Name "dotnet"
        Require-Command -Name "npm"
        Require-Command -Name "py"
        Set-Location -LiteralPath $root
        & $startScript
    }
    "stop" {
        Set-Location -LiteralPath $root
        & $stopScript
    }
    "restart" {
        Set-Location -LiteralPath $root
        & $stopScript
        Start-Sleep -Seconds 1
        Require-Command -Name "dotnet"
        Require-Command -Name "npm"
        Require-Command -Name "py"
        & $startScript
    }
    "status" {
        Show-Status
    }
}
