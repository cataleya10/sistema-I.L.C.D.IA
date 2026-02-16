# Portable Deploy Checklist (Local u Otro Equipo)

Checklist para mover el sistema entre equipos sin cambios de codigo.

## 1) Prerrequisitos

- Instalar .NET 8 SDK.
- Instalar Python 3.11+.
- Instalar Node 24 + npm 11.
- Tener PostgreSQL disponible (local o remoto).

## 2) Variables y secretos

- Copiar `.env.deploy.example` a `.env`.
- Definir:
  - `Jwt__SigningKey`
  - `PythonAi__ApiKey`
  - `API_KEY` (igual a `PythonAi__ApiKey`)
  - `ConnectionStrings__Default`
  - `PythonAi__BaseUrl`
- Validar:
  - `powershell -File scripts/validate-secrets.ps1 -RequireDbConnectionString`

## 3) Configuracion de frontend/runtime

- Definir URL API en runtime:
  - `powershell -File scripts/set-frontend-api-url.ps1 -ApiUrl "http://<api-host>:5000"`
- O usar configuracion unificada:
  - `powershell -File scripts/set-production-config.ps1 -FrontendApiUrl "http://<api-host>:5000" -AiBaseUrl "http://<ai-host>:8000" -FrontendOrigin "http://<frontend-host>:4200" -DbHost "<db-host>" -DbName "<db-name>" -DbUser "<db-user>" -DbPassword "<db-password>"`

## 4) Arranque de servicios

- AI engine:
  - `cd ai-engine-python`
  - `pip install -r requirements.txt`
  - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Backend:
  - `dotnet run --project backend-dotnet/src/Api`
- Frontend:
  - `cd frontend-angular/web`
  - `npm install`
  - `npm start`

## 5) Verificacion operativa

- Smoke:
  - `powershell -File scripts/smoke.ps1 -ApiBase "http://<api-host>:5000" -AiBase "http://<ai-host>:8000"`
- Umbrales:
  - `powershell -File scripts/check-operational-thresholds.ps1 -ApiBase "http://<api-host>:5000" -Username "<admin>" -Secret "<password>"`

## 6) Respaldo y recuperacion

- Backup:
  - `powershell -File scripts/backup-operational.ps1 -IncludeLogs -IncludeEnv`
- Restore:
  - `powershell -File scripts/restore-operational.ps1 -BackupPath ".\\backups\\<timestamp>" -Overwrite`

## 7) Criterio GO local

- `validate-secrets` en verde.
- `smoke` en verde.
- `processing_backlog=0` y sin errores de servidor.
- Documentos de prueba en `READY`.
