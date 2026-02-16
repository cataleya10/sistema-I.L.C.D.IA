param(
    [Parameter(Mandatory = $true)]
    [string]$FrontendApiUrl,
    [Parameter(Mandatory = $true)]
    [string]$AiBaseUrl,
    [Parameter(Mandatory = $true)]
    [string]$FrontendOrigin,
    [string]$DbHost = "",
    [int]$DbPort = 5432,
    [string]$DbName = "",
    [string]$DbUser = "",
    [string]$DbPassword = "",
    [switch]$SkipDatabase
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Normalize-Url {
    param([string]$value)
    $result = $value.Trim().TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($result)) {
        throw "URL invalida."
    }
    return $result
}

function Assert-DatabaseArgs {
    if ($SkipDatabase) {
        return
    }
    if (
        [string]::IsNullOrWhiteSpace($DbHost) -or
        [string]::IsNullOrWhiteSpace($DbName) -or
        [string]::IsNullOrWhiteSpace($DbUser) -or
        [string]::IsNullOrWhiteSpace($DbPassword)
    ) {
        throw "Faltan parametros de DB. Define DbHost/DbName/DbUser/DbPassword o usa -SkipDatabase."
    }
}

function Set-FrontendRuntimeConfig {
    param([string]$apiUrl)
    $configPath = Join-Path $root "frontend-angular\web\public\app-config.js"
    @"
window.__APP_CONFIG__ = {
  apiUrl: '$apiUrl'
};
"@ | Set-Content -Path $configPath -Encoding UTF8
    Write-Host "[OK] Updated $configPath" -ForegroundColor Green
}

function Set-BackendProductionConfig {
    param(
        [string]$aiUrl,
        [string]$origin,
        [string]$connectionString,
        [bool]$updateDb
    )
    $path = Join-Path $root "backend-dotnet\src\Api\appsettings.Production.json"
    if (-not (Test-Path $path)) {
        throw "No existe $path"
    }

    $json = Get-Content -Path $path -Raw | ConvertFrom-Json
    $json.Database.Provider = "Postgres"
    if ($updateDb) {
        $json.ConnectionStrings.Default = $connectionString
    }
    $json.PythonAi.BaseUrl = $aiUrl
    $json.Cors.AllowedOrigins = @($origin)

    $updated = $json | ConvertTo-Json -Depth 20
    Set-Content -Path $path -Value $updated -Encoding UTF8
    Write-Host "[OK] Updated $path" -ForegroundColor Green
}

$frontendApi = Normalize-Url -value $FrontendApiUrl
$aiBase = Normalize-Url -value $AiBaseUrl
$origin = Normalize-Url -value $FrontendOrigin

Assert-DatabaseArgs
$updateDb = -not $SkipDatabase
$connection = if ($updateDb) {
    "Host=$DbHost;Port=$DbPort;Database=$DbName;Username=$DbUser;Password=$DbPassword"
} else {
    ""
}

Set-FrontendRuntimeConfig -apiUrl $frontendApi
Set-BackendProductionConfig -aiUrl $aiBase -origin $origin -connectionString $connection -updateDb $updateDb

Write-Host ""
if ($updateDb) {
    Write-Host "Production config ready." -ForegroundColor Green
} else {
    Write-Host "Production config ready (DB pendiente)." -ForegroundColor Yellow
}
