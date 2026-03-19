param(
    [string]$ApiBase = "http://localhost:5000",
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Secret,
    [Parameter(Mandatory = $true)][string]$FolderPath,
    [int]$Limit = 100,
    [switch]$IssuesOnly,
    [switch]$NoRecurse,
    [switch]$FailOnIssues
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [string]$Label,
        [string]$Message,
        [string]$Color = "Cyan"
    )

    Write-Host "[$Label] $Message" -ForegroundColor $Color
}

function Resolve-ErrorMessage {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    if ($null -ne $ErrorRecord.ErrorDetails -and -not [string]::IsNullOrWhiteSpace($ErrorRecord.ErrorDetails.Message)) {
        return $ErrorRecord.ErrorDetails.Message
    }

    return $ErrorRecord.Exception.Message
}

$loginPayload = @{
    username = $Username
    password = $Secret
} | ConvertTo-Json

Write-Step -Label "INFO" -Message "Iniciando sesion en $ApiBase"
$login = Invoke-RestMethod -Uri "$ApiBase/api/auth/login" -Method Post -ContentType "application/json" -Body $loginPayload
$token = $login.token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "No se recibio token en la respuesta de login."
}

$headers = @{
    Authorization = "Bearer $token"
}

$auditPayload = @{
    folder_path = $FolderPath
    recurse = -not $NoRecurse
    limit = $Limit
    issues_only = [bool]$IssuesOnly
} | ConvertTo-Json

Write-Step -Label "INFO" -Message "Ejecutando auditoria de carpeta"

try {
    $audit = Invoke-RestMethod -Uri "$ApiBase/api/documents/diagnostics/audit-folder" -Method Post -Headers $headers -ContentType "application/json" -Body $auditPayload
}
catch {
    $message = Resolve-ErrorMessage -ErrorRecord $_
    Write-Step -Label "FAIL" -Message $message -Color "Red"
    exit 1
}

Write-Step -Label "OK" -Message "Auditoria completada" -Color "Green"
Write-Host ""
Write-Host "Carpeta           : $($audit.folder_path)"
Write-Host "Subcarpetas       : $($audit.recurse)"
Write-Host "Limite            : $($audit.limit)"
Write-Host "Issues only       : $($audit.issues_only)"
Write-Host "Archivos          : $($audit.matched_files)"
Write-Host "Procesados        : $($audit.processed_files)"
Write-Host "Documentos listado: $($audit.documents_returned)"
Write-Host "Limpios           : $($audit.clean_count)"
Write-Host "Issues            : $($audit.issue_count)"
Write-Host "Errores           : $($audit.error_count)"
Write-Host "Hard fail         : $($audit.hard_fail_count)"
Write-Host "No FACTURA        : $($audit.non_factura_count)"

if ($audit.document_type_counts) {
    Write-Host ""
    Write-Host "Tipos detectados:"
    $audit.document_type_counts.PSObject.Properties |
        Sort-Object Name |
        ForEach-Object {
            Write-Host ("- {0}: {1}" -f $_.Name, $_.Value)
        }
}

if ($audit.documents -and $audit.documents.Count -gt 0) {
    Write-Host ""
    Write-Host "Primeros documentos devueltos:"
    $audit.documents |
        Select-Object -First 10 |
        ForEach-Object {
            $warnings = if ($_.warning_count -gt 0) { " warnings=$($_.warning_count)" } else { "" }
            $hardFail = if ($_.hard_fail) { " hard_fail" } else { "" }
            Write-Host ("- {0} [{1}/{2}]{3}{4}" -f $_.name, $_.status, $_.document_type, $warnings, $hardFail)
        }
}

if ($FailOnIssues -and (($audit.issue_count -gt 0) -or ($audit.error_count -gt 0) -or ($audit.hard_fail_count -gt 0))) {
    Write-Step -Label "FAIL" -Message "La auditoria devolvio issues y se ejecuto con -FailOnIssues." -Color "Red"
    exit 2
}

exit 0
