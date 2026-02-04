param(
    [string]$ApiBase = "http://localhost:5000",
    [string]$AiBase = "http://localhost:8000",
    [string]$Username = "admin",
    [string]$Password = "Admin123!"
)

function Assert-Ok($name, $url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
            Write-Host "[OK] $name" -ForegroundColor Green
            return $true
        }
        Write-Host "[FAIL] $name ($($resp.StatusCode))" -ForegroundColor Red
        return $false
    } catch {
        Write-Host "[FAIL] $name ($($_.Exception.Message))" -ForegroundColor Red
        return $false
    }
}

Assert-Ok "API Health" "$ApiBase/health" | Out-Null
Assert-Ok "System Info" "$ApiBase/api/system/info" | Out-Null
Assert-Ok "AI Docs" "$AiBase/docs" | Out-Null

try {
    $login = Invoke-RestMethod -Uri "$ApiBase/api/auth/login" -Method Post -ContentType "application/json" -Body (@{
        username = $Username
        password = $Password
    } | ConvertTo-Json)
    if ($login.token) {
        Write-Host "[OK] Login" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Login (no token)" -ForegroundColor Red
    }
} catch {
    Write-Host "[FAIL] Login ($($_.Exception.Message))" -ForegroundColor Red
}
