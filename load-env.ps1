$envFiles = @(
    (Join-Path $PSScriptRoot ".env"),
    (Join-Path $PSScriptRoot ".env.backend")
)
foreach ($envPath in $envFiles) {
    if (-not (Test-Path $envPath)) { continue }
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $parts = $_.Split('=', 2)
        if ($parts.Length -eq 2) {
            # Unescape $$ → $ (Docker Compose escaping) for local execution
            $value = $parts[1].Trim() -replace '\$\$', '$'
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $value, 'Process')
        }
    }
}
