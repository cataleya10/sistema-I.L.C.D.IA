[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'CredentialFile')]
param(
    [Parameter(Mandatory = $true)]
    [string]$Folder,
    [string]$ApiUrl = "http://localhost:5000",
    [pscredential]$Credential,
    [string]$CredentialFile = "",
    [string]$OutDir = "$env:USERPROFILE\\Documents\\IA",
    [ValidateSet("generate","compare","none")]
    [string]$BaselineMode = "none",
    [string]$BaselinePath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Initialize-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-PdfFiles([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Folder not found: $Path"
    }
    return Get-ChildItem -Path $Path -Filter *.pdf -File
}

function New-Report([string]$Token, [array]$Docs) {
    $headers = @{ Authorization = "Bearer $Token" }
    $details = @()
    foreach ($doc in $Docs) {
        $detail = Invoke-RestMethod -Method Get -Uri "$ApiUrl/api/documents/$($doc.id)" -Headers $headers
        $details += [pscustomobject]@{
            name = $doc.name
            id = $doc.id
            status = $detail.status
            document_type = $detail.document_type
            confidence = $detail.confidence
            needs_review = $detail.needs_review
            fields = $detail.fields
        }
    }
    return $details
}

function New-FieldRows([array]$Details) {
    $rows = @()
    foreach ($d in $Details) {
        foreach ($f in $d.fields) {
            $rows += [pscustomobject]@{
                document_name = $d.name
                document_id = $d.id
                document_type = $d.document_type
                document_status = $d.status
                needs_review = $d.needs_review
                field_key = $f.key
                field_label = $f.label
                field_value = $f.value
                field_confidence = $f.confidence
                field_valid = $f.valid
                validation_errors = ($f.validation_errors -join "|")
                source_page = if ($f.source) { $f.source.page } else { $null }
                source_bbox = if ($f.source -and $f.source.bbox) { ($f.source.bbox -join ",") } else { "" }
            }
        }
    }
    return $rows
}

function New-Baseline([array]$Details) {
    $summary = @()
    foreach ($d in $Details) {
        $fieldKeys = @($d.fields | ForEach-Object { $_.key } | Sort-Object)
        $invalid = @($d.fields | Where-Object { $_.valid -eq $false })
        $low = @($d.fields | Where-Object { $_.confidence -lt 0.7 })
        $summary += [pscustomobject]@{
            document_name = $d.name
            document_type = $d.document_type
            field_keys = $fieldKeys
            invalid_count = $invalid.Count
            low_confidence_count = $low.Count
        }
    }
    return [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        summary = $summary
    }
}

function Compare-Baseline([array]$Details, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Baseline not found: $Path"
    }
    $baseline = Get-Content -Raw -Path $Path | ConvertFrom-Json
    $current = Build-Baseline -Details $Details
    $diffs = @()
    foreach ($cur in $current.summary) {
        $base = $baseline.summary | Where-Object { $_.document_name -eq $cur.document_name } | Select-Object -First 1
        if (-not $base) {
            $diffs += [pscustomobject]@{
                document_name = $cur.document_name
                change = "new_document"
            }
            continue
        }
        $baseKeys = @($base.field_keys)
        $curKeys = @($cur.field_keys)
        $missing = $baseKeys | Where-Object { $curKeys -notcontains $_ }
        $added = $curKeys | Where-Object { $baseKeys -notcontains $_ }
        if (@($missing).Count -gt 0 -or @($added).Count -gt 0 -or $cur.invalid_count -ne $base.invalid_count -or $cur.low_confidence_count -ne $base.low_confidence_count) {
            $diffs += [pscustomobject]@{
                document_name = $cur.document_name
                missing_fields = @($missing)
                added_fields = @($added)
                invalid_count = $cur.invalid_count
                low_confidence_count = $cur.low_confidence_count
            }
        }
    }
    return $diffs
}

Initialize-Directory $OutDir
$token = Get-AuthToken
$files = Get-PdfFiles $Folder

$uploads = @()
foreach ($file in $files) {
    $json = & curl.exe --silent --show-error -H "Authorization: Bearer $token" -F "file=@$($file.FullName)" "$ApiUrl/api/documents/upload"
    $obj = $json | ConvertFrom-Json
    $uploads += [pscustomobject]@{ name = $file.Name; id = $obj.id; status = $obj.status }
}

$headers = @{ Authorization = "Bearer $token" }
foreach ($u in $uploads) {
    Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/documents/$($u.id)/process" -Headers $headers | Out-Null
}

$details = New-Report -Token $token -Docs $uploads
$rows = New-FieldRows -Details $details

$stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$jsonPath = Join-Path $OutDir "review_results_$stamp.json"
$csvPath = Join-Path $OutDir "review_results_$stamp.csv"
$fieldsPath = Join-Path $OutDir "review_results_fields_$stamp.json"

$details | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath
$rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $csvPath
$rows | ConvertTo-Json -Depth 6 | Set-Content -Path $fieldsPath

if ($BaselineMode -eq "generate") {
    $baseline = New-Baseline -Details $details
    $baselinePath = if ($BaselinePath) { $BaselinePath } else { Join-Path $OutDir "baseline.json" }
    $baseline | ConvertTo-Json -Depth 6 | Set-Content -Path $baselinePath
}

if ($BaselineMode -eq "compare") {
    $comparePath = if ($BaselinePath) { $BaselinePath } else { Join-Path $OutDir "baseline.json" }
    $diffs = Compare-Baseline -Details $details -Path $comparePath
    $diffPath = Join-Path $OutDir "baseline_diff_$stamp.json"
    $diffs | ConvertTo-Json -Depth 6 | Set-Content -Path $diffPath
}

@{
    uploaded = $uploads.Count
    results_json = $jsonPath
    results_csv = $csvPath
    results_fields = $fieldsPath
} | ConvertTo-Json
