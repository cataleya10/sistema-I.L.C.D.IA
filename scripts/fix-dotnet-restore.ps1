param(
    [switch]$SkipApiRestore,
    [switch]$SkipTests,
    [string]$DotnetCliHome = "",
    [string]$NugetPackagesPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$infraTestsProject = Join-Path $root "backend-dotnet\tests\Infrastructure.Tests\Infrastructure.Tests.csproj"
$apiProject = Join-Path $root "backend-dotnet\src\Api\Api.csproj"

if ([string]::IsNullOrWhiteSpace($DotnetCliHome)) {
    $DotnetCliHome = Join-Path $root "backend-dotnet\tests\Infrastructure.Tests\.dotnet-cli-home"
}
if ([string]::IsNullOrWhiteSpace($NugetPackagesPath)) {
    $NugetPackagesPath = Join-Path $root "backend-dotnet\tests\Infrastructure.Tests\.nuget-packages"
}

$dotnetHome = $DotnetCliHome
$nugetPackages = $NugetPackagesPath

New-Item -ItemType Directory -Force -Path $dotnetHome | Out-Null
New-Item -ItemType Directory -Force -Path $nugetPackages | Out-Null

$env:DOTNET_CLI_HOME = $dotnetHome
$env:NUGET_PACKAGES = $nugetPackages
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"

# Ignore broken proxy settings from inherited shells/sessions.
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
$env:GIT_HTTP_PROXY = ""
$env:GIT_HTTPS_PROXY = ""

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [switch]$ContinueOnFailure
    )

    Write-Host "==> $Name" -ForegroundColor Cyan
    try {
        & $Action
        Write-Host "OK: $Name" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "FAIL: $Name" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        if (-not $ContinueOnFailure) {
            throw
        }
        return $false
    }
}

function Invoke-DotnetCommand {
    param([scriptblock]$Command)

    & $Command | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet command failed with exit code $LASTEXITCODE."
    }
}

Write-Host "DOTNET_CLI_HOME=$dotnetHome"
Write-Host "NUGET_PACKAGES=$nugetPackages"

$null = Invoke-Step -Name "Restore Infrastructure.Tests" -Action {
    Invoke-DotnetCommand { dotnet restore $infraTestsProject -m:1 -v:minimal }
}

$null = Invoke-Step -Name "Build Infrastructure.Tests" -Action {
    Invoke-DotnetCommand { dotnet build $infraTestsProject --no-restore -m:1 -v:minimal }
}

if (-not $SkipTests) {
    $null = Invoke-Step -Name "Test Infrastructure.Tests" -Action {
        Invoke-DotnetCommand { dotnet test $infraTestsProject --no-restore --no-build -m:1 -v:minimal }
    }
}

if (-not $SkipApiRestore) {
    $apiRestoreOk = Invoke-Step -Name "Restore API" -ContinueOnFailure -Action {
        Invoke-DotnetCommand { dotnet restore $apiProject -m:1 -v:minimal }
    }

    if ($apiRestoreOk) {
        $apiBuildOk = Invoke-Step -Name "Build API" -ContinueOnFailure -Action {
            Invoke-DotnetCommand { dotnet build $apiProject --no-restore -m:1 -v:minimal }
        }
        if (-not $apiBuildOk) {
            Write-Host "API build failed after restore. Check network/proxy/TLS and retry this script." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "API restore failed. This is usually network/proxy/certificate related." -ForegroundColor Yellow
        Write-Host "Infrastructure pipeline is healthy; API packages need reachable nuget.org." -ForegroundColor Yellow
    }
}

Write-Host "Dotnet repair finished." -ForegroundColor Green
