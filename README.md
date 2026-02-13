# Sistema I.L.C.D.IA

Sistema web empresarial para carga, clasificacion y extraccion de documentos oficiales con IA.

## Estructura
- frontend-angular/web (Angular 20)
- backend-dotnet/src (API .NET 8 por capas)
- ai-engine-python/app (FastAPI + PaddleOCR)

## Estado actual
- MVP funcional con persistencia EF Core (modo `InMemory` por defecto en desarrollo).
- Autenticacion JWT con login.
- Motor IA con OCR, clasificacion y extraccion por tipo.
- Procesamiento asincrono usando cola + worker con consulta de estado.
- Correccion manual de campos desde el frontend (Admin y User).
- Metricas basicas en `GET /api/system/metrics` (requests, errores, latencias).

## Requisitos
- Node 24.11.0 / npm 11.6.1
- .NET 8 SDK
- Python 3.11+

## Configuracion basica
- Copiar `.env.example` a `.env` y definir valores.
- JWT SigningKey: definir en `Jwt__SigningKey` con una clave fuerte.
- Llave compartida API->IA: definir el mismo valor en `PythonAi__ApiKey` y `API_KEY`.
- Refresh tokens persistentes: se almacenan en `storage/refresh_tokens.json`.
- Limpieza de archivos: configurar `Storage__RetentionDays` (>0 habilita borrado automatico).
- Usuarios JWT: configurar solo `PasswordHash` (no usar `Password` en texto plano).

## Arranque rapido (sin BD)
1) IA Engine
- Instalar dependencias: `pip install -r ai-engine-python/requirements.txt`
- Ejecutar: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

2) Backend API
- Ejecutar: `dotnet run --project backend-dotnet/src/Api`

3) Frontend
- Ejecutar: `npm install` en `frontend-angular/web`
- Ejecutar: `npm start`
- Staging: `npm run start:staging`
- Build staging: `npm run build:staging`
- Build produccion: `npm run build:prod`
- Configurar API runtime: editar `frontend-angular/web/public/app-config.js` o usar `powershell -File scripts/set-frontend-api-url.ps1 -ApiUrl "https://tu-api"`

## Smoke test
- Ejecutar: `powershell -File scripts/smoke.ps1`
- Con login: `powershell -File scripts/smoke.ps1 -Username "<usuario>" -Secret "<password>"`
- Modo protegido (auto-recupera y valida botones/endpoints): `powershell -File scripts/guard-mode.ps1 -Username "<usuario>" -Secret "<password>"`

## Verificacion local
- Ejecutar: `powershell -File scripts/verify-all.ps1`
- Rapido (sin frontend tests): `powershell -File scripts/verify-all.ps1 -SkipFrontendTests`
- Validar secretos: `powershell -File scripts/validate-secrets.ps1`
- Validar secretos + connection string DB: `powershell -File scripts/validate-secrets.ps1 -RequireDbConnectionString`
- Preflight release: `powershell -File scripts/release-preflight.ps1 -ApiBase "http://localhost:5000" -AiBase "http://localhost:8000" -Username "<usuario>" -Secret "<password>"`
- Preflight release con DB persistente: `powershell -File scripts/release-preflight.ps1 -RequireDbConnectionString -ApiBase "http://localhost:5000" -AiBase "http://localhost:8000" -Username "<usuario>" -Secret "<password>"`
- Check de umbrales operativos: `powershell -File scripts/check-operational-thresholds.ps1 -ApiBase "http://localhost:5000" -Username "<admin>" -Secret "<password>"`

## Flujo MVP (sin BD)
1) Cargar documento desde el frontend.
2) Procesar documento (la llamada espera la respuesta del motor IA).
3) Revisar y corregir campos si aplica.

## Rotacion de secretos
- Generar una llave JWT fuerte: `powershell -File scripts/generate-jwt-signing-key.ps1`
- Generar llave compartida API->IA: `powershell -File scripts/generate-shared-api-key.ps1`
- Asignar `Jwt__SigningKey` en `.env` o en variables del entorno del servidor.

## Contratos
Ver [docs/contracts.md](docs/contracts.md).

## Reglas OCR
Ver [docs/ocr-field-normalization.md](docs/ocr-field-normalization.md).

## Release Checklist
Ver [docs/release-checklist.md](docs/release-checklist.md).

## Backup / Restore
- Crear respaldo operativo: `powershell -File scripts/backup-operational.ps1 -IncludeLogs -IncludeEnv`
- Restaurar respaldo: `powershell -File scripts/restore-operational.ps1 -BackupPath ".\backups\<timestamp>" -Overwrite`

## Frontend por entorno
- `frontend-angular/web/src/environments/environment.development.ts`
- `frontend-angular/web/src/environments/environment.staging.ts`
- `frontend-angular/web/src/environments/environment.production.ts`
- La URL real de API se define en runtime con `frontend-angular/web/public/app-config.js`.
- Antes de desplegar staging/prod, definir `apiUrl` real en `app-config.js`.
