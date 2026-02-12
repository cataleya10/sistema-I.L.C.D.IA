param(
    [int]$Bytes = 48
)

if ($Bytes -lt 32) {
    throw "Usa al menos 32 bytes para una llave JWT segura."
}

$buffer = New-Object byte[] $Bytes
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $rng.GetBytes($buffer)
} finally {
    $rng.Dispose()
}
$key = [Convert]::ToBase64String($buffer).TrimEnd("=").Replace("+", "-").Replace("/", "_")

Write-Output "Jwt__SigningKey=$key"
