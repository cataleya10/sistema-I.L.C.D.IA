param(
    [string]$ApiBase = "http://localhost:5000",
    [Parameter(Mandatory = $true)]
    [string]$Username,
    [Parameter(Mandatory = $true)]
    [string]$Secret,
    [int]$MaxServerErrors = 0,
    [int]$MaxClientErrors = 50,
    [double]$MaxAvgDurationMs = 2000,
    [int]$MaxDurationMs = 8000,
    [int]$MaxProcessingBacklog = 50
)

$ErrorActionPreference = "Stop"

function Fail([string]$message) {
    throw $message
}

$login = Invoke-RestMethod -Uri "$ApiBase/api/auth/login" -Method Post -ContentType "application/json" -Body (@{
    username = $Username
    password = $Secret
} | ConvertTo-Json)

if (-not $login.token) {
    Fail "Login fallido: no se recibio token."
}

$headers = @{
    Authorization = "Bearer $($login.token)"
}

$metrics = Invoke-RestMethod -Uri "$ApiBase/api/system/metrics" -Headers $headers -Method Get
$processingDocs = Invoke-RestMethod -Uri "$ApiBase/api/documents?status=PROCESSING&page=1&pageSize=200" -Headers $headers -Method Get

$backlogCount = @($processingDocs).Count
$violations = @()

if ([int]$metrics.errors -gt $MaxServerErrors) {
    $violations += "errors=$($metrics.errors) > $MaxServerErrors"
}
if ([int]$metrics.client_errors -gt $MaxClientErrors) {
    $violations += "client_errors=$($metrics.client_errors) > $MaxClientErrors"
}
if ([double]$metrics.avg_duration_ms -gt $MaxAvgDurationMs) {
    $violations += "avg_duration_ms=$($metrics.avg_duration_ms) > $MaxAvgDurationMs"
}
if ([int]$metrics.max_duration_ms -gt $MaxDurationMs) {
    $violations += "max_duration_ms=$($metrics.max_duration_ms) > $MaxDurationMs"
}
if ($backlogCount -gt $MaxProcessingBacklog) {
    $violations += "processing_backlog=$backlogCount > $MaxProcessingBacklog"
}

Write-Host "Metrics snapshot:" -ForegroundColor Cyan
Write-Host "  requests=$($metrics.requests)"
Write-Host "  errors=$($metrics.errors)"
Write-Host "  client_errors=$($metrics.client_errors)"
Write-Host "  avg_duration_ms=$($metrics.avg_duration_ms)"
Write-Host "  max_duration_ms=$($metrics.max_duration_ms)"
Write-Host "  processing_backlog=$backlogCount"

if ($violations.Count -gt 0) {
    Fail ("Operational threshold check failed: " + ($violations -join "; "))
}

Write-Host "Operational threshold check passed." -ForegroundColor Green
