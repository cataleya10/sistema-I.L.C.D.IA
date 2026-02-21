param(
    [string]$ApiBase = "http://localhost:5000",
    [string]$Username = "",
    [string]$Secret = "",
    [string]$UsernameEnvVar = "ILCDIA_E2E_USERNAME",
    [string]$SecretEnvVar = "ILCDIA_E2E_SECRET",
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [string]$OutputDir = "reports/e2e-bbva",
    [int]$TimeoutSeconds = 180,
    [int]$PollIntervalSeconds = 2,
    [switch]$SkipForceFactura,
    [switch]$SkipTableAssertions,
    [switch]$SkipStrictFieldAssertions,
    [string]$ExpectedBank = "",
    [string]$ExpectedCuenta = "",
    [string]$ExpectedReferencia = "",
    [string]$ExpectedConcepto = "",
    [string]$ExpectedTotal = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Fail([string]$Message) {
    throw $Message
}

function Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Info([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Resolve-AbsolutePath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $root $PathValue))
}

function Get-EnvValue([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) {
        return ""
    }
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return ""
    }
    return $value.Trim()
}

function Resolve-Credentials {
    $resolvedUsername = if (-not [string]::IsNullOrWhiteSpace($Username)) { $Username.Trim() } else { Get-EnvValue -Name $UsernameEnvVar }
    $resolvedSecret = if (-not [string]::IsNullOrWhiteSpace($Secret)) { $Secret } else { Get-EnvValue -Name $SecretEnvVar }

    if ([string]::IsNullOrWhiteSpace($resolvedUsername)) {
        Fail "Username is required. Provide -Username or set environment variable '$UsernameEnvVar'."
    }
    if ([string]::IsNullOrWhiteSpace($resolvedSecret)) {
        Fail "Secret is required. Provide -Secret or set environment variable '$SecretEnvVar'."
    }

    return [pscustomobject]@{
        Username = $resolvedUsername
        Secret = $resolvedSecret
    }
}

function Get-FileContentType([string]$PathValue) {
    $extension = [System.IO.Path]::GetExtension($PathValue).ToLowerInvariant()
    switch ($extension) {
        ".pdf" { return "application/pdf" }
        ".png" { return "image/png" }
        ".jpg" { return "image/jpeg" }
        ".jpeg" { return "image/jpeg" }
        default { return "application/octet-stream" }
    }
}

function Get-StatusName($StatusValue) {
    if ($null -eq $StatusValue) {
        return ""
    }

    if ($StatusValue -is [string]) {
        if ([string]::IsNullOrWhiteSpace($StatusValue)) {
            return ""
        }
        return $StatusValue.Trim()
    }

    try {
        $numeric = [int]$StatusValue
        switch ($numeric) {
            0 { return "Uploaded" }
            1 { return "Processing" }
            2 { return "Ready" }
            3 { return "NeedsReview" }
            4 { return "Failed" }
            default { return $numeric.ToString() }
        }
    }
    catch {
        return $StatusValue.ToString()
    }
}

function Get-PropertyValue(
    [object]$Object,
    [string]$Name
) {
    if ($null -eq $Object -or [string]::IsNullOrWhiteSpace($Name)) {
        return $null
    }

    if ($Object -is [System.Collections.IDictionary]) {
        foreach ($key in $Object.Keys) {
            if ([string]::Equals([string]$key, $Name, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $Object[$key]
            }
        }
        return $null
    }

    $property = $Object.PSObject.Properties |
        Where-Object { [string]::Equals($_.Name, $Name, [System.StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if ($null -eq $property) {
        return $null
    }

    return $property.Value
}

function Get-FirstNonEmpty([string[]]$Values) {
    foreach ($value in $Values) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }
    return ""
}

function Get-ObjectString(
    [object]$Object,
    [string[]]$Names
) {
    foreach ($name in $Names) {
        $raw = Get-PropertyValue -Object $Object -Name $name
        if ($null -eq $raw) {
            continue
        }

        $text = $raw.ToString()
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            return $text.Trim()
        }
    }
    return ""
}

function Read-ResponseBody([System.Net.Http.HttpResponseMessage]$Response) {
    if ($null -eq $Response -or $null -eq $Response.Content) {
        return ""
    }
    return $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
}

function Assert-Success(
    [System.Net.Http.HttpResponseMessage]$Response,
    [string]$StepName
) {
    if ($Response.IsSuccessStatusCode) {
        return
    }

    $body = Read-ResponseBody -Response $Response
    $status = [int]$Response.StatusCode
    Fail "$StepName failed with HTTP $status. Body: $body"
}

function Normalize-Amount([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    return ($Value.ToLowerInvariant() -replace "[\s,\$]", "").Trim()
}

function Assert-TextContains(
    [string]$Text,
    [string]$Expected,
    [string]$Context
) {
    if ([string]::IsNullOrWhiteSpace($Expected)) {
        return
    }

    if ($Text.IndexOf($Expected, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Fail "$Context does not include expected value '$Expected'."
    }
}

function Assert-AmountContains(
    [string]$Text,
    [string]$Expected,
    [string]$Context
) {
    if ([string]::IsNullOrWhiteSpace($Expected)) {
        return
    }

    $normalizedText = Normalize-Amount -Value $Text
    $normalizedExpected = Normalize-Amount -Value $Expected
    if ([string]::IsNullOrWhiteSpace($normalizedExpected)) {
        return
    }
    if ($normalizedText.IndexOf($normalizedExpected, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Fail "$Context does not include expected amount '$Expected'."
    }
}

function Assert-ValueMatchesExpected(
    [string]$FieldName,
    [string]$Actual,
    [string]$Expected,
    [switch]$Amount
) {
    if ([string]::IsNullOrWhiteSpace($Expected)) {
        return
    }

    if ($Amount) {
        if ((Normalize-Amount -Value $Actual) -ne (Normalize-Amount -Value $Expected)) {
            Fail "Field '$FieldName' mismatch. Expected '$Expected', actual '$Actual'."
        }
        return
    }

    if (-not [string]::Equals($Actual.Trim(), $Expected.Trim(), [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "Field '$FieldName' mismatch. Expected '$Expected', actual '$Actual'."
    }
}

function Assert-RequiredCriticalValues(
    [System.Collections.IDictionary]$Values
) {
    $missing = @()
    foreach ($key in @("banco", "cuenta", "referencia", "concepto", "total")) {
        $value = [string]$Values[$key]
        if ([string]::IsNullOrWhiteSpace($value)) {
            $missing += $key
        }
    }

    if ($missing.Count -gt 0) {
        Fail "Missing critical mapped values in tabla_celdas: $($missing -join ', ')."
    }
}

function Get-TablaCeldasPayload([object]$DocumentDetail) {
    $fields = @(Get-PropertyValue -Object $DocumentDetail -Name "fields")
    if ($fields.Count -eq 0) {
        Fail "Document detail does not include fields."
    }

    $tableField = $null
    foreach ($field in $fields) {
        $key = Get-ObjectString -Object $field -Names @("key")
        if ([string]::Equals($key, "tabla_celdas", [System.StringComparison]::OrdinalIgnoreCase)) {
            $tableField = $field
            break
        }
    }

    if ($null -eq $tableField) {
        Fail "Document detail does not include 'tabla_celdas'."
    }

    $raw = Get-FirstNonEmpty @(
        (Get-ObjectString -Object $tableField -Names @("correctedValue")),
        (Get-ObjectString -Object $tableField -Names @("value"))
    )
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Fail "Field 'tabla_celdas' is empty."
    }

    try {
        return $raw | ConvertFrom-Json
    }
    catch {
        Fail "Field 'tabla_celdas' is not valid JSON."
    }
}

function Build-CriticalValuesFromTabla([object]$TablaPayload) {
    $mapped = Get-PropertyValue -Object $TablaPayload -Name "mapped_fields"

    $actual = [ordered]@{
        banco = Get-FirstNonEmpty @(
            (Get-ObjectString -Object $mapped -Names @("banco", "bank")),
            (Get-ObjectString -Object $TablaPayload -Names @("bank"))
        )
        cuenta = Get-FirstNonEmpty @(
            (Get-ObjectString -Object $mapped -Names @("cuenta", "cuenta_beneficiario", "cuenta_retiro"))
        )
        referencia = Get-FirstNonEmpty @(
            (Get-ObjectString -Object $mapped -Names @("referencia"))
        )
        concepto = Get-FirstNonEmpty @(
            (Get-ObjectString -Object $mapped -Names @("concepto", "concepto_pago"))
        )
        total = Get-FirstNonEmpty @(
            (Get-ObjectString -Object $mapped -Names @("total", "importe", "importe_detectado"))
        )
    }

    Assert-ValueMatchesExpected -FieldName "banco" -Actual $actual["banco"] -Expected $ExpectedBank
    Assert-ValueMatchesExpected -FieldName "cuenta" -Actual $actual["cuenta"] -Expected $ExpectedCuenta
    Assert-ValueMatchesExpected -FieldName "referencia" -Actual $actual["referencia"] -Expected $ExpectedReferencia
    Assert-ValueMatchesExpected -FieldName "concepto" -Actual $actual["concepto"] -Expected $ExpectedConcepto
    Assert-ValueMatchesExpected -FieldName "total" -Actual $actual["total"] -Expected $ExpectedTotal -Amount

    $resolved = [ordered]@{
        banco = Get-FirstNonEmpty @($ExpectedBank, $actual["banco"])
        cuenta = Get-FirstNonEmpty @($ExpectedCuenta, $actual["cuenta"])
        referencia = Get-FirstNonEmpty @($ExpectedReferencia, $actual["referencia"])
        concepto = Get-FirstNonEmpty @($ExpectedConcepto, $actual["concepto"])
        total = Get-FirstNonEmpty @($ExpectedTotal, $actual["total"])
    }

    return [pscustomobject]@{
        Actual = $actual
        Resolved = $resolved
    }
}

function Assert-TablaStructure(
    [object]$TablaPayload,
    [switch]$SkipChecks
) {
    if ($SkipChecks) {
        return
    }

    $rows = Get-PropertyValue -Object $TablaPayload -Name "rows"
    if ($null -eq $rows -or @($rows).Count -lt 2) {
        Fail "tabla_celdas.rows does not include header + data rows."
    }

    $bank = Get-ObjectString -Object $TablaPayload -Names @("bank")
    if ([string]::IsNullOrWhiteSpace($bank)) {
        Fail "tabla_celdas.bank is empty."
    }
}

function Get-Json(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url,
    [string]$Token
) {
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
    $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    $response = $Client.SendAsync($request).GetAwaiter().GetResult()
    Assert-Success -Response $response -StepName "GET $Url"
    $raw = Read-ResponseBody -Response $response
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Post-Json(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url,
    [string]$Token,
    [string]$BodyJson
) {
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $Url)
    $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    $request.Content = [System.Net.Http.StringContent]::new($BodyJson, [System.Text.Encoding]::UTF8, "application/json")
    $response = $Client.SendAsync($request).GetAwaiter().GetResult()
    Assert-Success -Response $response -StepName "POST $Url"
    $raw = Read-ResponseBody -Response $response
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Post-FileUpload(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url,
    [string]$Token,
    [string]$UploadPath
) {
    $bytes = [System.IO.File]::ReadAllBytes($UploadPath)
    $filename = [System.IO.Path]::GetFileName($UploadPath)
    $contentType = Get-FileContentType -PathValue $UploadPath

    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse($contentType)
    $multipart.Add($fileContent, "file", $filename)

    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $Url)
    $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    $request.Content = $multipart
    $response = $Client.SendAsync($request).GetAwaiter().GetResult()
    Assert-Success -Response $response -StepName "POST $Url"
    $raw = Read-ResponseBody -Response $response
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Download-Bytes(
    [System.Net.Http.HttpClient]$Client,
    [string]$Url,
    [string]$Token
) {
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
    $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)
    $response = $Client.SendAsync($request).GetAwaiter().GetResult()
    Assert-Success -Response $response -StepName "GET $Url"
    return $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
}

function Assert-WordPayload(
    [byte[]]$WordBytes,
    [System.Collections.IDictionary]$ExpectedValues,
    [switch]$SkipTableChecks,
    [switch]$SkipFieldChecks
) {
    $text = [System.Text.Encoding]::UTF8.GetString($WordBytes)
    if (-not $text.Contains("SISTEMA DE LECTURA INTELIGENTE")) {
        Fail "Word export does not include expected report header."
    }
    if (-not $text.Contains("Campos")) {
        Fail "Word export does not include extracted fields section."
    }
    if ($text.IndexOf("mapped_fields", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Fail "Word export leaked raw mapped_fields JSON."
    }
    if (-not $SkipTableChecks -and $text.IndexOf("Tabla estructurada", [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        Fail "Word export does not include the structured table summary (expected for BBVA-like payment receipts)."
    }
    if (-not $SkipFieldChecks) {
        Assert-TextContains -Text $text -Expected $ExpectedValues["banco"] -Context "Word export"
        Assert-TextContains -Text $text -Expected $ExpectedValues["cuenta"] -Context "Word export"
        Assert-TextContains -Text $text -Expected $ExpectedValues["referencia"] -Context "Word export"
        Assert-TextContains -Text $text -Expected $ExpectedValues["concepto"] -Context "Word export"
        Assert-AmountContains -Text $text -Expected $ExpectedValues["total"] -Context "Word export"
    }
}

function Assert-ExcelPayload(
    [byte[]]$ExcelBytes,
    [System.Collections.IDictionary]$ExpectedValues,
    [switch]$SkipTableChecks,
    [switch]$SkipFieldChecks
) {
    if ($ExcelBytes.Length -lt 512) {
        Fail "Excel export is unexpectedly small."
    }

    $memory = [System.IO.MemoryStream]::new($ExcelBytes)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new($memory, [System.IO.Compression.ZipArchiveMode]::Read, $false)
        try {
            $sheetEntry = $zip.GetEntry("xl/worksheets/sheet1.xml")
            if ($null -eq $sheetEntry) {
                Fail "Excel export does not contain xl/worksheets/sheet1.xml."
            }
            $reader = [System.IO.StreamReader]::new($sheetEntry.Open())
            try {
                $xml = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }

            if ($xml.IndexOf("Campo", [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
                Fail "Excel export does not include the expected header row."
            }
            if ($xml.IndexOf("mapped_fields", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Fail "Excel export leaked raw mapped_fields JSON."
            }
            if (-not $SkipTableChecks -and $xml.IndexOf("Tabla estructurada", [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
                Fail "Excel export does not include the structured table summary (expected for BBVA-like payment receipts)."
            }
            if (-not $SkipFieldChecks) {
                Assert-TextContains -Text $xml -Expected $ExpectedValues["banco"] -Context "Excel export"
                Assert-TextContains -Text $xml -Expected $ExpectedValues["cuenta"] -Context "Excel export"
                Assert-TextContains -Text $xml -Expected $ExpectedValues["referencia"] -Context "Excel export"
                Assert-TextContains -Text $xml -Expected $ExpectedValues["concepto"] -Context "Excel export"
                Assert-AmountContains -Text $xml -Expected $ExpectedValues["total"] -Context "Excel export"
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $memory.Dispose()
    }
}

try {
    $credentials = Resolve-Credentials
    $resolvedFilePath = Resolve-AbsolutePath -PathValue $FilePath
    if (-not (Test-Path $resolvedFilePath)) {
        Fail "File not found: $resolvedFilePath"
    }

    $resolvedOutputDir = Resolve-AbsolutePath -PathValue $OutputDir
    New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

    $apiRoot = $ApiBase.TrimEnd("/")
    Info "API base: $apiRoot"
    Info "Input file: $resolvedFilePath"
    Info "Output dir: $resolvedOutputDir"
    Info "Username: $($credentials.Username)"

    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)

    try {
        Info "Authenticating user..."
        $loginBody = @{
            username = $credentials.Username
            password = $credentials.Secret
        } | ConvertTo-Json

        $loginRequest = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, "$apiRoot/api/auth/login")
        $loginRequest.Content = [System.Net.Http.StringContent]::new($loginBody, [System.Text.Encoding]::UTF8, "application/json")
        $loginResponse = $client.SendAsync($loginRequest).GetAwaiter().GetResult()
        Assert-Success -Response $loginResponse -StepName "POST $apiRoot/api/auth/login"
        $loginJson = (Read-ResponseBody -Response $loginResponse) | ConvertFrom-Json
        $token = $loginJson.token
        if ([string]::IsNullOrWhiteSpace($token)) {
            Fail "Login succeeded but no token was returned."
        }
        Ok "Authentication succeeded."

        Info "Uploading document..."
        $upload = Post-FileUpload -Client $client -Url "$apiRoot/api/documents/upload" -Token $token -UploadPath $resolvedFilePath
        if ($null -eq $upload -or [string]::IsNullOrWhiteSpace($upload.id)) {
            Fail "Upload response does not include document id."
        }
        $documentId = [string]$upload.id
        Ok "Document uploaded with id $documentId"

        Info "Triggering processing..."
        $processPayload = "{}"
        if (-not $SkipForceFactura) {
            $processPayload = @{ forceDocumentType = "FACTURA" } | ConvertTo-Json
        }
        $processResponse = Post-Json -Client $client -Url "$apiRoot/api/documents/$documentId/process" -Token $token -BodyJson $processPayload
        $initialStatus = Get-StatusName -StatusValue $processResponse.status
        if (-not [string]::IsNullOrWhiteSpace($initialStatus)) {
            Info "Initial process status: $initialStatus"
        }

        $terminalStatuses = @("Ready", "NeedsReview", "Failed")
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $current = $processResponse
        $currentStatus = Get-StatusName -StatusValue $current.status

        while ($terminalStatuses -notcontains $currentStatus) {
            if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                Fail "Timeout waiting for process completion. Last status: $currentStatus"
            }
            Start-Sleep -Seconds $PollIntervalSeconds
            $current = Get-Json -Client $client -Url "$apiRoot/api/documents/$documentId/process/status" -Token $token
            $currentStatus = Get-StatusName -StatusValue $current.status
            Info "Processing status: $currentStatus"
        }

        if ($currentStatus -eq "Failed") {
            $errorsText = ""
            if ($null -ne $current.errors) {
                $errorsText = ($current.errors | ForEach-Object { $_.ToString() }) -join "; "
            }
            Fail "Document processing failed. Errors: $errorsText"
        }
        Ok "Processing completed with status $currentStatus"

        $documentDetail = Get-Json -Client $client -Url "$apiRoot/api/documents/$documentId" -Token $token
        $tablaPayload = Get-TablaCeldasPayload -DocumentDetail $documentDetail
        Assert-TablaStructure -TablaPayload $tablaPayload -SkipChecks:$SkipTableAssertions
        $criticalBundle = Build-CriticalValuesFromTabla -TablaPayload $tablaPayload
        if (-not $SkipStrictFieldAssertions) {
            Assert-RequiredCriticalValues -Values $criticalBundle.Actual
        }
        $criticalValues = $criticalBundle.Resolved
        Info ("Critical mapped values: banco='{0}', cuenta='{1}', referencia='{2}', concepto='{3}', total='{4}'" -f `
                $criticalValues["banco"], $criticalValues["cuenta"], $criticalValues["referencia"], $criticalValues["concepto"], $criticalValues["total"])

        Info "Downloading Word export..."
        $wordBytes = Download-Bytes -Client $client -Url "$apiRoot/api/documents/$documentId/export/word" -Token $token
        $wordPath = Join-Path $resolvedOutputDir "$documentId.doc"
        [System.IO.File]::WriteAllBytes($wordPath, $wordBytes)
        Assert-WordPayload -WordBytes $wordBytes -ExpectedValues $criticalValues -SkipTableChecks:$SkipTableAssertions -SkipFieldChecks:$SkipStrictFieldAssertions
        Ok "Word export saved: $wordPath"

        Info "Downloading Excel export..."
        $excelBytes = Download-Bytes -Client $client -Url "$apiRoot/api/documents/$documentId/export/excel" -Token $token
        $excelPath = Join-Path $resolvedOutputDir "$documentId.xlsx"
        [System.IO.File]::WriteAllBytes($excelPath, $excelBytes)
        Assert-ExcelPayload -ExcelBytes $excelBytes -ExpectedValues $criticalValues -SkipTableChecks:$SkipTableAssertions -SkipFieldChecks:$SkipStrictFieldAssertions
        Ok "Excel export saved: $excelPath"

        Write-Host ""
        Write-Host "BBVA export E2E passed." -ForegroundColor Green
    }
    finally {
        $client.Dispose()
    }
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
