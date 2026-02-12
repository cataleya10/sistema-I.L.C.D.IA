param(
    [string]$DestinationRoot = "backups",
    [switch]$IncludeLogs = $true,
    [switch]$IncludeEnv
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $root (Join-Path $DestinationRoot $timestamp)
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$stagingRoot = Join-Path $backupDir "_staging"
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

$script:items = @()

function Add-ArchiveItem {
    param(
        [string]$SourcePath,
        [string]$TargetRelativePath,
        [string]$ArchiveName
    )

    if (-not (Test-Path $SourcePath)) {
        return
    }

    $archivePath = Join-Path $backupDir $ArchiveName

    $isDirectory = Test-Path $SourcePath -PathType Container

    try {
        if ($isDirectory) {
            $stagePath = Join-Path $stagingRoot ([IO.Path]::GetFileNameWithoutExtension($ArchiveName))
            if (Test-Path $stagePath) {
                Remove-Item -Path $stagePath -Recurse -Force
            }
            New-Item -ItemType Directory -Path $stagePath -Force | Out-Null

            & robocopy $SourcePath $stagePath /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -gt 7) {
                throw "robocopy failed with exit code $LASTEXITCODE for $SourcePath"
            }

            if ((Get-ChildItem -Path $stagePath -Recurse -File | Measure-Object).Count -eq 0) {
                Write-Warning "No files copied from $SourcePath. Skipping archive."
                return
            }

            Compress-Archive -Path (Join-Path $stagePath "*") -DestinationPath $archivePath -Force
        } else {
            Compress-Archive -Path $SourcePath -DestinationPath $archivePath -Force
        }
    } catch {
        Write-Warning "Failed to backup '$SourcePath': $($_.Exception.Message)"
        return
    }

    $script:items += @{
        source_path = $SourcePath
        target_relative_path = $TargetRelativePath
        archive = $ArchiveName
        is_directory = $isDirectory
    }
}

Add-ArchiveItem -SourcePath (Join-Path $root "storage") -TargetRelativePath "storage" -ArchiveName "storage.zip"
Add-ArchiveItem -SourcePath (Join-Path $root "backend-dotnet\src\Api\storage") -TargetRelativePath "backend-dotnet\src\Api\storage" -ArchiveName "api-storage.zip"
if ($IncludeLogs) {
    Add-ArchiveItem -SourcePath (Join-Path $root "logs") -TargetRelativePath "logs" -ArchiveName "logs.zip"
}
if ($IncludeEnv) {
    Add-ArchiveItem -SourcePath (Join-Path $root ".env") -TargetRelativePath ".env" -ArchiveName "env.zip"
}

$manifest = @{
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    root = $root
    items = $script:items
}

$manifestPath = Join-Path $backupDir "manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding UTF8

if ((Get-ChildItem -Path $backupDir -Filter *.zip | Measure-Object).Count -eq 0) {
    throw "No se generaron respaldos ZIP."
}

if (Test-Path $stagingRoot) {
    Remove-Item -Path $stagingRoot -Recurse -Force
}

Write-Host "Backup created at: $backupDir" -ForegroundColor Green
Write-Host "Manifest: $manifestPath" -ForegroundColor Green
