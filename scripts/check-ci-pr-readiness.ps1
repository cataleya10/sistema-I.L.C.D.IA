param(
    [Parameter(Mandatory = $true)]
    [string]$Repo,
    [Parameter(Mandatory = $true)]
    [string]$Branch,
    [string]$Commit = "",
    [string]$GitHubToken = "",
    [switch]$RequireCleanWorktree
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

function Warn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Get-RemoteHost {
    $remoteUrl = (git remote get-url origin).Trim()
    if ([string]::IsNullOrWhiteSpace($remoteUrl)) {
        return ""
    }
    if ($remoteUrl -match "^https?://([^/]+)/") {
        return $Matches[1].ToLowerInvariant()
    }
    if ($remoteUrl -match "^[^@]+@([^:]+):") {
        return $Matches[1].ToLowerInvariant()
    }
    return ""
}

if ([string]::IsNullOrWhiteSpace($Commit)) {
    $Commit = (git rev-parse HEAD).Trim()
}

if ([string]::IsNullOrWhiteSpace($Commit)) {
    Fail "No se pudo resolver el commit actual."
}

Write-Host "Repo:   $Repo"
Write-Host "Branch: $Branch"
Write-Host "Commit: $Commit"
$remoteHost = Get-RemoteHost
if (-not [string]::IsNullOrWhiteSpace($remoteHost)) {
    Write-Host "Remote: $remoteHost"
}

$statusLines = git status --short
if ($RequireCleanWorktree -and $statusLines) {
    Fail "Worktree no limpio. Confirma/commitea cambios antes de validar release."
}
if ($statusLines) {
    Warn "Worktree con cambios locales. CI remoto debe evaluarse sobre el commit publicado."
} else {
    Ok "Worktree limpio."
}

if ([string]::IsNullOrWhiteSpace($GitHubToken)) {
    $GitHubToken = $env:GITHUB_TOKEN
}

if ([string]::IsNullOrWhiteSpace($GitHubToken)) {
    if ($remoteHost -like "*gitlab*") {
        Warn "Repo en GitLab y sin token API. Valida CI/MR en UI de GitLab."
        Write-Host "UI checks (GitLab):"
        Write-Host "1) MR aprobado hacia branch '$Branch'"
        Write-Host "2) Branch protegida (Settings > Repository > Protected branches)"
        Write-Host "3) Pipeline en verde (jobs equivalentes a security/backend/frontend/ai-engine)"
    } else {
        Warn "Sin GITHUB_TOKEN. No se puede validar CI/PR por API. Usa UI de GitHub."
        Write-Host "UI checks (GitHub):"
        Write-Host "1) PR aprobado en branch '$Branch'"
        Write-Host "2) Proteccion de rama activa"
        Write-Host "3) Checks en verde: security, backend, frontend, ai-engine"
    }
    exit 0
}

$headers = @{
    Authorization = "Bearer $GitHubToken"
    Accept = "application/vnd.github+json"
    "User-Agent" = "release-readiness-script"
}

$repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo" -Headers $headers -Method Get
Ok ("Repositorio accesible: " + $repoInfo.full_name)

$runs = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/actions/runs?branch=$Branch&per_page=20" -Headers $headers -Method Get
if (-not $runs.workflow_runs -or $runs.workflow_runs.Count -eq 0) {
    Fail "No se encontraron workflow runs para branch '$Branch'."
}

$matchingRun = $runs.workflow_runs | Where-Object { $_.head_sha -eq $Commit } | Select-Object -First 1
if (-not $matchingRun) {
    Fail "No hay workflow run para el commit $Commit en branch $Branch."
}

Write-Host ("Run CI: " + $matchingRun.html_url)
if ($matchingRun.status -ne "completed") {
    Fail "Workflow run no completado. Estado: $($matchingRun.status)"
}
if ($matchingRun.conclusion -ne "success") {
    Fail "Workflow run sin exito. Conclusion: $($matchingRun.conclusion)"
}
Ok "Workflow run principal en verde."

$jobs = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/actions/runs/$($matchingRun.id)/jobs?per_page=100" -Headers $headers -Method Get
$requiredJobs = @("security", "backend", "frontend", "ai-engine")
foreach ($jobName in $requiredJobs) {
    $job = $jobs.jobs | Where-Object { $_.name -eq $jobName } | Select-Object -First 1
    if (-not $job) {
        Fail "No se encontro job requerido: $jobName"
    }
    if ($job.conclusion -ne "success") {
        Fail "Job '$jobName' no exitoso. Conclusion: $($job.conclusion)"
    }
    Ok "Job '$jobName' en verde."
}

$prs = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/pulls?state=open&head=$($Repo.Split('/')[0]):$Branch&per_page=20" -Headers $headers -Method Get
if (-not $prs -or $prs.Count -eq 0) {
    Warn "No hay PR abierto detectado para '$Branch'. Si release es por merge directo, valida governance manualmente."
    exit 0
}

$pr = $prs | Select-Object -First 1
Write-Host ("PR: " + $pr.html_url)

$reviews = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/pulls/$($pr.number)/reviews?per_page=100" -Headers $headers -Method Get
$approved = $reviews | Where-Object { $_.state -eq "APPROVED" } | Select-Object -First 1
if (-not $approved) {
    Fail "PR sin aprobaciones."
}
Ok "PR con al menos una aprobacion."

Warn "La proteccion de rama se confirma en Settings > Branches (policy de GitHub)."
Write-Host "CI/PR readiness check completado." -ForegroundColor Green
