param(
    [string]$ApiBase = "http://localhost:5000",
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Secret
)

$ErrorActionPreference = "Stop"

function Show-Result {
    param(
        [string]$Name,
        [string]$Code,
        [string[]]$Expected
    )
    if ($Expected -contains $Code) {
        Write-Host "[OK]   $Name -> $Code" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Name -> $Code (esperado: $($Expected -join ', '))" -ForegroundColor Red
    }
}

function Invoke-Code {
    param(
        [string]$Method,
        [string]$Url,
        [string]$Token = "",
        [string]$Body = ""
    )
    $args = @("--silent", "--output", "NUL", "--write-out", "%{http_code}", "-X", $Method, $Url)
    if ($Token) {
        $args += @("-H", "Authorization: Bearer $Token")
    }
    if ($Body) {
        $args += @("-H", "Content-Type: application/json", "-d", $Body)
    }
    return (& curl.exe @args).Trim()
}

$loginPayload = @{
    username = $Username
    password = $Secret
} | ConvertTo-Json

$login = Invoke-RestMethod -Uri "$ApiBase/api/auth/login" -Method Post -ContentType "application/json" -Body $loginPayload
$token = $login.token
$refresh = $login.refresh_token
if (-not $refresh) { $refresh = $login.refreshToken }

if (-not $token) {
    throw "No se recibio token en login."
}

$tempFile = Join-Path $env:TEMP "ui-actions-check.pdf"
[System.IO.File]::WriteAllBytes($tempFile, [byte[]](37,80,68,70,45,49,46,52,10,37,226,227,207,211,10))
$uploadJson = & curl.exe --silent --show-error -H "Authorization: Bearer $token" -F "file=@$tempFile;type=application/pdf" "$ApiBase/api/documents/upload"
$uploaded = $uploadJson | ConvertFrom-Json
$docId = $uploaded.id

if (-not $docId) {
    throw "No se recibio id al subir documento."
}

Show-Result "GET /api/documents" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents" -Token $token) @("200")
Show-Result "GET /api/documents/{id}" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId" -Token $token) @("200")
Show-Result "GET /api/documents/{id}/file" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId/file" -Token $token) @("200")
Show-Result "POST /api/documents/{id}/process" (Invoke-Code -Method "POST" -Url "$ApiBase/api/documents/$docId/process" -Token $token -Body "{}") @("200", "202")
Show-Result "GET /api/documents/{id}/process/status" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId/process/status" -Token $token) @("200")
Show-Result "POST /api/documents/{id}/reprocess" (Invoke-Code -Method "POST" -Url "$ApiBase/api/documents/$docId/reprocess" -Token $token -Body "{}") @("200", "202")
Show-Result "GET /api/documents/{id}/logs" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId/logs" -Token $token) @("200")
Show-Result "GET /api/documents/{id}/export/word" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId/export/word" -Token $token) @("200")
Show-Result "GET /api/documents/{id}/export/excel" (Invoke-Code -Method "GET" -Url "$ApiBase/api/documents/$docId/export/excel" -Token $token) @("200")
Show-Result "GET /api/system/info" (Invoke-Code -Method "GET" -Url "$ApiBase/api/system/info" -Token $token) @("200")
Show-Result "GET /api/system/metrics" (Invoke-Code -Method "GET" -Url "$ApiBase/api/system/metrics" -Token $token) @("200")

$firstDelete = Invoke-Code -Method "DELETE" -Url "$ApiBase/api/documents/$docId" -Token $token
Show-Result "DELETE /api/documents/{id} (primer intento)" $firstDelete @("204", "409")
if ($firstDelete -eq "409") {
    Start-Sleep -Seconds 3
    Show-Result "DELETE /api/documents/{id} (reintento)" (Invoke-Code -Method "DELETE" -Url "$ApiBase/api/documents/$docId" -Token $token) @("204")
}

$logoutBody = @{ refresh_token = $refresh } | ConvertTo-Json
try {
    Invoke-RestMethod -Uri "$ApiBase/api/auth/logout" -Method Post -ContentType "application/json" -Body $logoutBody | Out-Null
    Show-Result "POST /api/auth/logout" "204" @("204")
}
catch {
    if ($_.Exception.Response) {
        Show-Result "POST /api/auth/logout" "$([int]$_.Exception.Response.StatusCode)" @("204")
    } else {
        Show-Result "POST /api/auth/logout" "ERR" @("204")
    }
}
