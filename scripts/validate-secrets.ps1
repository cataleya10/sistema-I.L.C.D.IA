param(
    [switch]$RequireDbConnectionString
)

$ErrorActionPreference = "Stop"

function Get-EnvValue {
    param([string]$Name)
    return [Environment]::GetEnvironmentVariable($Name, "Process")
}

function Assert-StrongValue {
    param(
        [string]$Name,
        [int]$MinLength = 24
    )

    $value = (Get-EnvValue -Name $Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Name no esta definido."
    }

    if ($value.ToUpperInvariant().Contains("CHANGE_ME")) {
        throw "$Name contiene placeholder CHANGE_ME."
    }

    if ($value.Length -lt $MinLength) {
        throw "$Name es demasiado corto. Minimo: $MinLength caracteres."
    }
}

function Assert-MatchingSharedKeys {
    $apiBackend = (Get-EnvValue -Name "PythonAi__ApiKey")
    $apiAi = (Get-EnvValue -Name "API_KEY")
    if ([string]::IsNullOrWhiteSpace($apiBackend) -or [string]::IsNullOrWhiteSpace($apiAi)) {
        throw "PythonAi__ApiKey y API_KEY deben estar definidos."
    }
    if ($apiBackend -ne $apiAi) {
        throw "PythonAi__ApiKey y API_KEY deben ser iguales para autenticar API->IA."
    }
}

function Assert-DbConnectionString {
    $conn = Get-EnvValue -Name "ConnectionStrings__Default"
    if ([string]::IsNullOrWhiteSpace($conn)) {
        throw "ConnectionStrings__Default no esta definido."
    }
    if ($conn.ToUpperInvariant().Contains("CHANGE_ME")) {
        throw "ConnectionStrings__Default contiene placeholder CHANGE_ME."
    }
}

Assert-StrongValue -Name "Jwt__SigningKey" -MinLength 32
Assert-StrongValue -Name "PythonAi__ApiKey" -MinLength 24
Assert-StrongValue -Name "API_KEY" -MinLength 24
Assert-MatchingSharedKeys

if ($RequireDbConnectionString) {
    Assert-DbConnectionString
}

Write-Host "Secrets validation passed." -ForegroundColor Green
