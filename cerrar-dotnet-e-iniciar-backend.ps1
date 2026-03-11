# Cierra todos los procesos .NET que puedan bloquear DLLs
Get-Process | Where-Object { $_.ProcessName -like "dotnet*" } | ForEach-Object { Stop-Process -Id $_.Id -Force }

# Espera unos segundos para liberar archivos
Start-Sleep -Seconds 3

# Inicia el backend desde la carpeta correcta
cd "backend-dotnet\src\Api"
dotnet run
