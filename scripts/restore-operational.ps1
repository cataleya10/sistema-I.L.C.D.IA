param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$DestinationRoot = ".",
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path $BackupPath)) {
    throw "BackupPath no existe: $BackupPath"
}

$resolvedBackup = Resolve-Path $BackupPath | Select-Object -ExpandProperty Path
$manifestPath = Join-Path $resolvedBackup "manifest.json"
if (-not (Test-Path $manifestPath)) {
    throw "manifest.json no encontrado en: $resolvedBackup"
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$destinationRootCandidate = Join-Path $root $DestinationRoot
if (-not (Test-Path $destinationRootCandidate)) {
    New-Item -ItemType Directory -Path $destinationRootCandidate -Force | Out-Null
}
$destinationRootPath = Resolve-Path $destinationRootCandidate | Select-Object -ExpandProperty Path

foreach ($item in $manifest.items) {
    $archivePath = Join-Path $resolvedBackup ([string]$item.archive)
    if (-not (Test-Path $archivePath)) {
        throw "Archivo de respaldo no encontrado: $archivePath"
    }

    $relative = [string]$item.target_relative_path
    $targetPath = Join-Path $destinationRootPath $relative

    if (Test-Path $targetPath) {
        if (-not $Overwrite) {
            throw "Destino ya existe: $targetPath. Usa -Overwrite para reemplazar."
        }

        Remove-Item -Path $targetPath -Recurse -Force
    }

    $isDirectory = [bool]$item.is_directory
    if ($isDirectory) {
        New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        Expand-Archive -Path $archivePath -DestinationPath $targetPath -Force
    } else {
        $parentPath = Split-Path -Parent $targetPath
        if (-not [string]::IsNullOrWhiteSpace($parentPath)) {
            New-Item -ItemType Directory -Path $parentPath -Force | Out-Null
        }
        Expand-Archive -Path $archivePath -DestinationPath $parentPath -Force
    }
}

Write-Host "Restore completed from: $resolvedBackup" -ForegroundColor Green
