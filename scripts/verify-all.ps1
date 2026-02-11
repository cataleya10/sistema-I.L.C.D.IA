param(
    [switch]$SkipFrontendTests
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

try {
    Invoke-Step -Name "Backend build (.NET Release)" -Action {
        Push-Location $root
        try {
            & dotnet build "backend-dotnet\Backend.slnx" -c Release
            Assert-LastExitCode "Backend build failed."
        } finally {
            Pop-Location
        }
    }

    if (-not $SkipFrontendTests) {
        Invoke-Step -Name "Frontend tests (Angular/Karma)" -Action {
            Push-Location (Join-Path $root "frontend-angular\web")
            try {
                & npm.cmd test -- --watch=false --browsers=ChromeHeadless
                Assert-LastExitCode "Frontend tests failed."
            } finally {
                Pop-Location
            }
        }
    } else {
        Write-Host "[SKIP] Frontend tests" -ForegroundColor Yellow
    }

    Invoke-Step -Name "Python tests (AI engine)" -Action {
        Push-Location (Join-Path $root "ai-engine-python")
        try {
            & .\.venv312\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
            Assert-LastExitCode "Python tests failed."
        } finally {
            Pop-Location
        }
    }

    Write-Host ""
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
