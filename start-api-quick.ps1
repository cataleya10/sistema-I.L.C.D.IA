param(
    [switch]$NoBuild = $true,
    [switch]$Force
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiPath = Join-Path $root "backend-dotnet\src\Api"
. "$root\load-env.ps1"

if ($Force) {
    $listeners = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $pids) {
            try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch {}
        }
        Start-Sleep -Milliseconds 400
    }
}

$env:DOTNET_CLI_HOME = Join-Path $env:TEMP "ilcdia-dotnet-home"
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"
$env:MSBuildEnableWorkloadResolver = "false"
$env:ASPNETCORE_ENVIRONMENT = "Development"

if ([string]::IsNullOrWhiteSpace($env:Jwt__SigningKey) -or $env:Jwt__SigningKey.Length -lt 32) {
    $env:Jwt__SigningKey = "DevSigningKey_ThisMustBeAtLeast32Chars_2026"
}

Set-Location -LiteralPath $apiPath

Write-Host "Starting API on http://localhost:5000 ..." -ForegroundColor Cyan
if ($NoBuild) {
    dotnet run --no-build --launch-profile http
} else {
    dotnet run --launch-profile http
}
