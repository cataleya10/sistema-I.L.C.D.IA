param(
    [string]$ApiBase = "http://localhost:5000",
    [string]$AiBase = "http://localhost:8000",
    [string]$Username = "",
    [string]$Secret = "",
    [string]$BbvaFilePath = "",
    [switch]$SkipFrontendTests,
    [switch]$RequireDbConnectionString,
    [switch]$SkipBbvaE2E
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

    if (-not $SkipBbvaE2E) {
        $bbvaUsername = if (-not [string]::IsNullOrWhiteSpace($Username)) { $Username.Trim() } else { $env:ILCDIA_E2E_USERNAME }
        $bbvaSecret = if (-not [string]::IsNullOrWhiteSpace($Secret)) { $Secret } else { $env:ILCDIA_E2E_SECRET }

        if ([string]::IsNullOrWhiteSpace($bbvaUsername) -or [string]::IsNullOrWhiteSpace($bbvaSecret) -or [string]::IsNullOrWhiteSpace($BbvaFilePath)) {
            Write-Host "[SKIP] BBVA export E2E (define -BbvaFilePath y credenciales via -Username/-Secret o ILCDIA_E2E_USERNAME/ILCDIA_E2E_SECRET)" -ForegroundColor Yellow
        } else {
            Invoke-Step -Name "BBVA export E2E (process + word + excel)" -Action {
                Push-Location $root
                $previousUsername = $env:ILCDIA_E2E_USERNAME
                $previousSecret = $env:ILCDIA_E2E_SECRET
                try {
                    $env:ILCDIA_E2E_USERNAME = $bbvaUsername
                    $env:ILCDIA_E2E_SECRET = $bbvaSecret
                    & powershell -File "scripts\e2e-bbva-export.ps1" `
                        -ApiBase $ApiBase `
                        -FilePath $BbvaFilePath
                    Assert-LastExitCode "e2e-bbva-export.ps1 failed."
                } finally {
                    $env:ILCDIA_E2E_USERNAME = $previousUsername
                    $env:ILCDIA_E2E_SECRET = $previousSecret
                    Pop-Location
                }
            }
        }
    } else {
        Write-Host "[SKIP] BBVA export E2E" -ForegroundColor Yellow
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
