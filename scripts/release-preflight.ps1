param(
    [string]$ApiBase = "http://localhost:5000",
    [string]$AiBase = "http://localhost:8000",
    [string]$Username = "",
    [string]$Secret = "",
    [switch]$SkipFrontendTests,
    [switch]$RequireDbConnectionString
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Action
    Write-Host "[OK] $Name" -ForegroundColor Green
}

function Assert-LastExitCode {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Invoke-VulnerabilityScan {
    $projects = Get-ChildItem (Join-Path $root "backend-dotnet\src") -Recurse -Filter *.csproj |
        Select-Object -ExpandProperty FullName

    foreach ($project in $projects) {
        Write-Host "Scanning vulnerabilities: $project" -ForegroundColor DarkCyan
        $output = dotnet list $project package --vulnerable --include-transitive --format json | Out-String
        $hasVulnerabilities = ($output -match '"severity"\s*:') -or ($output -match '"advisoryurl"\s*:')
        if ($hasVulnerabilities) {
            Write-Host $output -ForegroundColor Red
            throw "Se detectaron vulnerabilidades en paquetes NuGet."
        }
    }
}

try {
    Invoke-Step -Name "Load environment variables" -Action {
        Push-Location $root
        try {
            . .\load-env.ps1
            if ($RequireDbConnectionString) {
                & powershell -File "scripts\validate-secrets.ps1" -RequireDbConnectionString
            } else {
                & powershell -File "scripts\validate-secrets.ps1"
            }
            Assert-LastExitCode "validate-secrets.ps1 failed."
        } finally {
            Pop-Location
        }
    }

    Invoke-Step -Name "Code verification (build + tests)" -Action {
        Push-Location $root
        try {
            if ($SkipFrontendTests) {
                & powershell -File "scripts\verify-all.ps1" -SkipFrontendTests
            } else {
                & powershell -File "scripts\verify-all.ps1"
            }
            Assert-LastExitCode "verify-all.ps1 failed."
        } finally {
            Pop-Location
        }
    }

    Invoke-Step -Name "NuGet vulnerability scan" -Action {
        Invoke-VulnerabilityScan
    }

    Invoke-Step -Name "Smoke test (runtime)" -Action {
        Push-Location $root
        try {
            if ([string]::IsNullOrWhiteSpace($Username) -or [string]::IsNullOrWhiteSpace($Secret)) {
                & powershell -File "scripts\smoke.ps1" -ApiBase $ApiBase -AiBase $AiBase
            } else {
                & powershell -File "scripts\smoke.ps1" -ApiBase $ApiBase -AiBase $AiBase -Username $Username -Secret $Secret
            }
            Assert-LastExitCode "smoke.ps1 failed."
        } finally {
            Pop-Location
        }
    }

    Write-Host ""
    Write-Host "Release preflight passed." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
