[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'CredentialFile')]
param(
    [Parameter(Mandatory = $true)]
    [string]$Folder,
    [string]$ApiUrl = "http://localhost:5000",
    [pscredential]$Credential,
    [string]$CredentialFile = "",
    [string]$OutDir = "$env:USERPROFILE\\Documents\\IA",
    [int]$IntervalSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Initialize-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-AuthToken {
    if (-not $Credential) {
        if ($CredentialFile -and (Test-Path -LiteralPath $CredentialFile)) {
            $script:Credential = Import-Clixml -Path $CredentialFile
        } else {
            $script:Credential = Get-Credential -Message "Credenciales para el API"
        }
    }
    $body = @{
        username = $Credential.UserName
        password = $Credential.GetNetworkCredential().Password
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/auth/login" -ContentType "application/json" -Body $body
    return $resp.token
}

Initialize-Directory $OutDir
$statePath = Join-Path $OutDir "batch_watch_state.json"
$state = @{}
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -Raw -Path $statePath | ConvertFrom-Json
}

while ($true) {
    $token = Get-AuthToken
    $headers = @{ Authorization = "Bearer $token" }
    $files = Get-ChildItem -Path $Folder -Filter *.pdf -File
    foreach ($file in $files) {
        $key = $file.FullName
        if ($state.PSObject.Properties.Name -contains $key) {
            continue
        }
        $state | Add-Member -NotePropertyName $key -NotePropertyValue (Get-Date).ToString("s") -Force
        $state | ConvertTo-Json | Set-Content -Path $statePath

        $json = & curl.exe --silent --show-error -H "Authorization: Bearer $token" -F "file=@$($file.FullName)" "$ApiUrl/api/documents/upload"
        $obj = $json | ConvertFrom-Json
        Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/documents/$($obj.id)/process" -Headers $headers | Out-Null
    }
    Start-Sleep -Seconds $IntervalSeconds
}
