param(
    [Parameter(Mandatory = $true)]
    [string]$ApiUrl
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "frontend-angular\web\public\app-config.js"

$normalized = $ApiUrl.Trim().TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($normalized)) {
    throw "ApiUrl es requerido."
}

@"
window.__APP_CONFIG__ = {
  apiUrl: '$normalized'
};
"@ | Set-Content -Path $configPath -Encoding UTF8

Write-Host "Updated $configPath with apiUrl=$normalized" -ForegroundColor Green
