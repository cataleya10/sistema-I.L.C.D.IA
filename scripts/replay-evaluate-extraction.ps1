param(
    [string]$PythonExe = "c:\xampp\htdocs\Sistema I.L.C.D.IA\ai-engine-python\.venv312\Scripts\python.exe",
    [string]$AiRoot = "c:\xampp\htdocs\Sistema I.L.C.D.IA\ai-engine-python",
    [string]$DatasetJsonl = "C:\Users\100156643\Documents\IA\training_dataset.jsonl",
    [string]$LabelsJson = "C:\Users\100156643\Documents\IA\labels_prefilled.json",
    [string]$BaselineReportJson = "C:\Users\100156643\Documents\IA\evaluation_report.json",
    [string]$OutDir = "c:\xampp\htdocs\Sistema I.L.C.D.IA\ai-engine-python\artifacts\replay-eval",
    [switch]$OpenOutDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Exists([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name no encontrado: $Path"
    }
}

function Get-SummaryMap([object]$Report) {
    $map = @{}
    foreach ($item in @($Report.summary)) {
        $map[[string]$item.field] = $item
    }
    return $map
}

Assert-Exists $PythonExe "Python"
Assert-Exists $AiRoot "Carpeta ai-engine-python"
Assert-Exists $DatasetJsonl "Dataset JSONL"
Assert-Exists $LabelsJson "Labels JSON"
Assert-Exists $BaselineReportJson "Reporte baseline"
Assert-Exists (Join-Path $AiRoot "tools\replay_dataset_extraction.py") "Script replay_dataset_extraction.py"
Assert-Exists (Join-Path $AiRoot "tools\evaluate_extraction.py") "Script evaluate_extraction.py"

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$replayedDataset = Join-Path $OutDir "training_dataset_replayed_$stamp.jsonl"
$newReport = Join-Path $OutDir "evaluation_report_replayed_$stamp.json"
$summaryCsv = Join-Path $OutDir "evaluation_summary_$stamp.csv"
$failuresCsv = Join-Path $OutDir "evaluation_failures_$stamp.csv"

Write-Host "== Replay de extraccion =="
Push-Location $AiRoot
try {
    $env:DATASET_JSONL = $DatasetJsonl
    $env:OUTPUT_JSONL = $replayedDataset
    & $PythonExe "tools\replay_dataset_extraction.py" | Out-Host

    Write-Host "== Evaluacion de extraccion =="
    $env:LABELS_JSON = $LabelsJson
    $env:DATASET_JSONL = $replayedDataset
    $env:REPORT_JSON = $newReport
    & $PythonExe "tools\evaluate_extraction.py" | Out-Host
}
finally {
    Pop-Location
}

Write-Host "== Comparativo =="
$old = Get-Content -Raw -LiteralPath $BaselineReportJson | ConvertFrom-Json
$new = Get-Content -Raw -LiteralPath $newReport | ConvertFrom-Json
$oldMap = Get-SummaryMap $old
$newMap = Get-SummaryMap $new

$allKeys = @($oldMap.Keys + $newMap.Keys | Sort-Object -Unique)
$rows = @()
foreach ($key in $allKeys) {
    $o = $oldMap[$key]
    $n = $newMap[$key]
    $oldAcc = if ($o) { [double]$o.accuracy } else { $null }
    $newAcc = if ($n) { [double]$n.accuracy } else { $null }
    $rows += [pscustomobject]@{
        field = $key
        old_accuracy = $oldAcc
        new_accuracy = $newAcc
        delta = if ($oldAcc -ne $null -and $newAcc -ne $null) { [math]::Round($newAcc - $oldAcc, 6) } else { $null }
        old_total = if ($o) { [int]$o.total } else { 0 }
        new_total = if ($n) { [int]$n.total } else { 0 }
    }
}

$rows |
    Sort-Object field |
    Format-Table -AutoSize field, old_accuracy, new_accuracy, delta, old_total, new_total

$rows |
    Sort-Object field |
    Export-Csv -NoTypeInformation -Encoding UTF8 -Path $summaryCsv

$failures = @()
foreach ($doc in @($new.per_doc)) {
    foreach ($f in @($doc.fields)) {
        if (-not [bool]$f.ok) {
            $failures += [pscustomobject]@{
                document_id = $doc.document_id
                filename = $doc.filename
                key = $f.key
                expected = $f.expected
                predicted = $f.predicted
            }
        }
    }
}

if ($failures.Count -eq 0) {
    Write-Host "Pendientes: 0 (sin fallas)" -ForegroundColor Green
    Set-Content -Path $failuresCsv -Encoding UTF8 -Value "document_id,filename,key,expected,predicted"
} else {
    Write-Host "Pendientes: $($failures.Count)" -ForegroundColor Yellow
    $failures | Sort-Object filename, key | Format-Table -AutoSize document_id, filename, key, expected, predicted
    $failures | Sort-Object filename, key | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $failuresCsv
}

Write-Host ""
Write-Host "Salida:"
Write-Host " - Dataset replay: $replayedDataset"
Write-Host " - Reporte replay: $newReport"
Write-Host " - Resumen CSV: $summaryCsv"
Write-Host " - Pendientes CSV: $failuresCsv"

if ($OpenOutDir) {
    Write-Host "Abriendo carpeta de salida..."
    Start-Process explorer.exe $OutDir | Out-Null
}
