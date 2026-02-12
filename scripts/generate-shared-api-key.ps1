param(
    [int]$Bytes = 48
)

if ($Bytes -lt 24) {
    throw "Usa al menos 24 bytes para una API key segura."
}

$buffer = New-Object byte[] $Bytes
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $rng.GetBytes($buffer)
} finally {
    $rng.Dispose()
}

$key = [Convert]::ToBase64String($buffer).TrimEnd("=").Replace("+", "-").Replace("/", "_")

Write-Output "PythonAi__ApiKey=$key"
Write-Output "API_KEY=$key"
