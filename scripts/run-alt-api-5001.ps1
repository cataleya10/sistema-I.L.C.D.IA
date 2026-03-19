param(
    [string]$ApiDllPath = "c:\xampp\htdocs\Sistema I.L.C.D.IA\backend-dotnet\.tmp\apirun\Api.dll",
    [string]$RootPath = "c:\xampp\htdocs\Sistema I.L.C.D.IA",
    [string]$ContentRoot = "c:\xampp\htdocs\Sistema I.L.C.D.IA\backend-dotnet\src\Api",
    [string]$Urls = "http://127.0.0.1:5001"
)

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            return
        }

        $parts = $line -split '=', 2
        if ($parts.Length -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        # Unescape $$ -> $ to match the repo's local env-loading behavior.
        $value = ($parts[1].Trim() -replace '\$\$', '$').Trim('"')
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

Set-Location $RootPath
Import-DotEnv (Join-Path $RootPath '.env')
Import-DotEnv (Join-Path $RootPath '.env.backend')

$env:ASPNETCORE_URLS = $Urls
$env:ASPNETCORE_ENVIRONMENT = 'Development'
$env:DOTNET_CLI_HOME = Join-Path $RootPath '.dotnet-cli'

& dotnet $ApiDllPath --contentRoot $ContentRoot
