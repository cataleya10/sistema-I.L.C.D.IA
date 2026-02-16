# Pre-Production Readiness Report - 2026-02-16

Proyecto: `Sistema I.L.C.D.IA`  
Fecha de validacion: `2026-02-16`  
Commit local evaluado: `1eb4eae63fa8b4a6aa6e8061263271700c34a719`

## Resultado Ejecutivo

Estado actual: **NO-GO para produccion publica**, **GO para entorno local/staging tecnico**.

Motivo principal de NO-GO:
1. Configuracion productiva aun apunta a `localhost`/placeholders.
2. CI/MR/proteccion de rama no verificados por API remota en esta sesion.
3. Bloque de base de datos productiva sigue pendiente (acordado previamente).

## Evidencia Tecnica Ejecutada (2026-02-16)

1. Validacion de secretos:
   - Comando: `powershell -File scripts/validate-secrets.ps1`
   - Resultado: `Secrets validation passed.`

2. Smoke runtime:
   - Comando: `powershell -File scripts/smoke.ps1 -ApiBase "http://localhost:5000" -AiBase "http://localhost:8000"`
   - Resultado:
     - `API Health`: OK
     - `System Info`: OK
     - `AI Docs`: OK

3. Umbrales operativos:
   - Comando: `powershell -File scripts/check-operational-thresholds.ps1 -ApiBase "http://localhost:5000" -Username "admin" -Secret "Admin123!" -MaxServerErrors 0 -MaxClientErrors 400 -MaxAvgDurationMs 3000 -MaxDurationMs 12000 -MaxProcessingBacklog 200`
   - Resultado: `Operational threshold check passed.`
   - Snapshot:
     - `requests=346`
     - `errors=0`
     - `client_errors=2`
     - `avg_duration_ms=38.47`
     - `max_duration_ms=3721`
     - `processing_backlog=0`

4. Auditoria de documentos cargados:
   - Total: `8`
   - `READY`: `8`
   - `NEEDS_REVIEW`: `0`

5. Gate CI/PR remoto:
   - Comando: `powershell -File scripts/check-ci-pr-readiness.ps1 -Repo "sicae.360.ia/iddocumentos" -Branch "main"`
   - Resultado: pendiente por API/token remoto (validacion manual requerida en GitLab UI).

## Hallazgos de Configuracion (bloqueantes para produccion)

1. Frontend runtime API aun local:
   - `frontend-angular/web/public/app-config.js` -> `http://localhost:5000`

2. Backend production config con placeholders/local:
   - `backend-dotnet/src/Api/appsettings.Production.json`
   - `ConnectionStrings:Default` con `CHANGE_ME`
   - `PythonAi:BaseUrl` en `http://localhost:8000`
   - `Cors:AllowedOrigins` en `http://localhost:4200`
   - `Jwt:SigningKey` con `CHANGE_ME_USE_ENV`

3. `.env` local no incluye `ConnectionStrings__Default` para DB persistente productiva.

## Semaforo por Bloque

1. Calidad funcional OCR/extraccion: **VERDE**
2. Estabilidad operativa local (health/smoke/metricas): **VERDE**
3. Seguridad minima de secretos locales: **VERDE**
4. Configuracion real de produccion (URLs/DB/CORS/JWT env): **ROJO**
5. CI/MR/proteccion de rama remoto: **AMARILLO** (validacion manual pendiente)
6. Plan de rollback firmado con versiones reales: **AMARILLO**

## Cierre para pasar a GO (orden recomendado)

1. Definir URLs reales:
   - Frontend origin publico
   - API backend publica
   - AI engine publica

2. Completar DB productiva:
   - `ConnectionStrings__Default` real
   - Validar con: `powershell -File scripts/validate-secrets.ps1 -RequireDbConnectionString`

3. Aplicar configuracion de produccion:
   - `powershell -File scripts/set-production-config.ps1 -FrontendApiUrl "<api-url>" -AiBaseUrl "<ai-url>" -FrontendOrigin "<frontend-origin>" -DbHost "<host>" -DbName "<db>" -DbUser "<user>" -DbPassword "<pass>"`

4. Ejecutar preflight final:
   - `powershell -File scripts/release-preflight.ps1 -RequireDbConnectionString -ApiBase "<api-url>" -AiBase "<ai-url>" -Username "<usuario>" -Secret "<password>"`

5. Cerrar governance en GitLab UI:
   - MR aprobado
   - Branch protegida
   - Pipeline verde (security/backend/frontend/ai-engine)

