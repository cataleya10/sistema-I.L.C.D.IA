param(
    [string]$labelsJson = "C:\Users\100156643\Documents\IA\labels_template.json",
    [string]$docsPath = "C:\Users\100156643\Documents\IA",
    [string]$outputJson = "C:\Users\100156643\Documents\IA\labels_prefilled.json",
    [string]$outputCsv = "C:\Users\100156643\Documents\IA\labels_prefilled.csv",
    [string]$aiUrl = "http://localhost:8000/process-document"
)

Add-Type -AssemblyName System.Net.Http

if (-not (Test-Path $labelsJson)) {
    Write-Host "Labels template not found: $labelsJson" -ForegroundColor Red
    exit 1
}

$labels = Get-Content $labelsJson -Raw | ConvertFrom-Json

function Invoke-AiProcess {
    param([string]$filePath, [string]$documentId)

    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(300)

    $content = New-Object System.Net.Http.MultipartFormDataContent
    $fileStream = [System.IO.File]::OpenRead($filePath)
    try {
        $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
        $content.Add($fileContent, "file", [System.IO.Path]::GetFileName($filePath))
        $content.Add((New-Object System.Net.Http.StringContent($documentId)), "document_id")
        $content.Add((New-Object System.Net.Http.StringContent("local")), "source")

        $response = $client.PostAsync($aiUrl, $content).Result
        $body = $response.Content.ReadAsStringAsync().Result
        if (-not $response.IsSuccessStatusCode) {
            throw "HTTP $($response.StatusCode): $body"
        }
        return $body | ConvertFrom-Json
    }
    finally {
        $fileStream.Dispose()
        $content.Dispose()
        $client.Dispose()
    }
}

foreach ($doc in $labels) {
    $filePath = Join-Path $docsPath $doc.filename
    if (-not (Test-Path $filePath)) {
        Write-Host "Missing file: $filePath" -ForegroundColor Yellow
        continue
    }

    Write-Host "Processing $($doc.filename)..." -ForegroundColor Cyan
    try {
        $response = Invoke-AiProcess -filePath $filePath -documentId $doc.document_id
    } catch {
        Write-Host "Failed: $($doc.filename) -> $($_.Exception.Message)" -ForegroundColor Red
        continue
    }

    if ($null -eq $response.fields) {
        continue
    }

    $fieldMap = @{}
    foreach ($field in $response.fields) {
        if ($field.key -and $field.value) {
            $fieldMap[$field.key] = $field.value
        }
    }

    foreach ($key in $doc.fields.PSObject.Properties.Name) {
        if (-not $doc.fields.$key -and $fieldMap.ContainsKey($key)) {
            $doc.fields.$key = $fieldMap[$key]
        }
    }
}

$labels | ConvertTo-Json -Depth 6 | Set-Content $outputJson

$rows = @()
foreach ($doc in $labels) {
    foreach ($key in $doc.fields.PSObject.Properties.Name) {
        $rows += [PSCustomObject]@{
            document_id = $doc.document_id
            filename = $doc.filename
            document_type = $doc.document_type
            field_key = $key
            field_label = $key
            field_value = $doc.fields.$key
        }
    }
}

$rows | Export-Csv -Path $outputCsv -NoTypeInformation -Encoding UTF8

Write-Host "Prefilled labels saved to $outputJson" -ForegroundColor Green
Write-Host "Prefilled CSV saved to $outputCsv" -ForegroundColor Green
