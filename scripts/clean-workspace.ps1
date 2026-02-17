param(
    [switch]$IncludeLogs = $true,
    [switch]$IncludeReports = $true,
    [switch]$IncludePythonCaches = $true,
    [switch]$IncludeDotnetTestCaches = $true,
    [switch]$IncludeDotnetBuildArtifacts = $true,
    [switch]$IncludeFrontendArtifacts = $true,
    [switch]$IncludePidFiles = $true
)

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$removed = New-Object System.Collections.Generic.List[string]

function Remove-IfExists {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $Path)) {
            $removed.Add($Path)
        }
    }
}

if ($IncludeReports) {
    if (Test-Path "reports") {
        Get-ChildItem "reports" -Force | ForEach-Object {
            Remove-IfExists $_.FullName
        }
    }
}

if ($IncludeLogs) {
    foreach ($logDir in @(
        "logs",
        "ai-engine-python/logs",
        "backend-dotnet/logs",
        "backend-dotnet/src/Api/logs",
        "frontend-angular/web/logs"
    )) {
        if (Test-Path $logDir) {
            Get-ChildItem $logDir -Force | ForEach-Object {
                Remove-IfExists $_.FullName
            }
        }
    }
}

if ($IncludeDotnetTestCaches) {
    Remove-IfExists "backend-dotnet/tests/Infrastructure.Tests/.dotnet-cli-home"
    Remove-IfExists "backend-dotnet/tests/Infrastructure.Tests/.nuget-packages"
}

if ($IncludeDotnetBuildArtifacts) {
    Get-ChildItem "backend-dotnet" -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("bin", "obj") } |
        ForEach-Object { Remove-IfExists $_.FullName }
}

if ($IncludeFrontendArtifacts) {
    Remove-IfExists "frontend-angular/web/.angular/cache"
}

if ($IncludePidFiles) {
    Remove-IfExists "start-all.pids.json"
}

if ($IncludePythonCaches) {
    Get-ChildItem "ai-engine-python" -Recurse -Directory -Filter "__pycache__" |
        Where-Object { $_.FullName -notmatch "\\.venv312\\" -and $_.FullName -notmatch "\\.venv\\" } |
        ForEach-Object { Remove-IfExists $_.FullName }

    Get-ChildItem "ai-engine-python" -Recurse -File -Include "*.pyc","*.pyo" |
        Where-Object { $_.FullName -notmatch "\\.venv312\\" -and $_.FullName -notmatch "\\.venv\\" } |
        ForEach-Object { Remove-IfExists $_.FullName }
}

Write-Output ("Removed items: {0}" -f $removed.Count)
if ($removed.Count -gt 0) {
    $removed | Select-Object -First 100
}
