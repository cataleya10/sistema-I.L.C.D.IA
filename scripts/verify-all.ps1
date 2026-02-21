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

    Invoke-Step -Name "Backend tests (.NET Release)" -Action {
        Push-Location $root
        try {
            & dotnet test "backend-dotnet\Backend.slnx" -c Release --no-build --verbosity minimal
            Assert-LastExitCode "Backend tests failed."
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
            $python = ".\.venv312\Scripts\python.exe"
            if (-not (Test-Path $python)) {
                throw "Python virtual environment not found at ai-engine-python/.venv312."
            }

            & $python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pytest') else 1)"
            $hasPytest = $LASTEXITCODE -eq 0

            if ($hasPytest) {
                Write-Host "Using pytest..." -ForegroundColor DarkCyan
                & $python -m pytest tests -q -p no:cacheprovider
                Assert-LastExitCode "Python tests failed (pytest)."
            } else {
                Write-Host "pytest not found, falling back to unittest..." -ForegroundColor Yellow
                & $python -m unittest discover -s tests -p "test_*.py" -v
                Assert-LastExitCode "Python tests failed (unittest)."
            }
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
