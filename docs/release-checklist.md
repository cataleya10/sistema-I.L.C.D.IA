# Release Checklist (Go/No-Go)

Checklist operativo para validar salida a produccion de `Sistema I.L.C.D.IA`.

> **Estado actual**: 130 unit tests passing (106 extraction + 24 classify/validators).
> Rama: `release/readiness-final`. Ultima revision: 2026-02-17.

Evidencia recomendada:
- Reporte de readiness: `docs/release-readiness-2026-02-12.md`
- Plantilla de rollback: `docs/rollback-plan-template.md`

## 1) Gate Tecnico Previo

- [ ] Rama protegida y PR aprobado.
- [ ] CI en verde para backend, frontend y AI.
- [ ] Sin vulnerabilidades activas de paquetes.
- [x] Variables sensibles definidas fuera de codigo (`Jwt__SigningKey`, `PythonAi__ApiKey`, secretos de despliegue). *(`.env.production` validado con valores planos + NOTA de set-production-config.ps1)*
- [ ] URL de API frontend definida para el ambiente en `frontend-angular/web/public/app-config.js`.

Comando recomendado local:

```powershell
powershell -File scripts/release-preflight.ps1 -ApiBase "http://localhost:5000" -AiBase "http://localhost:8000" -Username "<usuario>" -Secret "<password>"
```

Verificacion CI/PR (si hay `GITHUB_TOKEN` disponible):

```powershell
powershell -File scripts/check-ci-pr-readiness.ps1 -Repo "<owner/repo>" -Branch "<branch>" -GitHubToken "$env:GITHUB_TOKEN"
```

Validacion rapida de secretos:

```powershell
powershell -File scripts/validate-secrets.ps1
```

Si usa PostgreSQL u otro proveedor persistente:

```powershell
powershell -File scripts/validate-secrets.ps1 -RequireDbConnectionString
```

## 2) Verificacion Funcional Minima

- [ ] Login correcto.
- [ ] Carga de documento correcta.
- [ ] Proceso asincrono correcto (`PROCESSING` -> `READY` o `NEEDS_REVIEW`).
- [ ] Edicion manual de campos y guardado correcto.
- [ ] Exportes Word/Excel correctos.

Endpoints de referencia:
- `GET /health`
- `GET /api/system/info`
- `GET /api/documents/{id}/process/status`

## 3) Observabilidad y Operacion

- [ ] Log de API activo en `backend-dotnet/src/Api/logs/api.log`.
- [ ] Correlation ID visible en respuestas y logs.
- [ ] Metricas disponibles en `GET /api/system/metrics` (requiere Admin).
- [ ] Alertas basicas preparadas para errores 5xx, latencia alta y backlog de procesamiento.

Chequeo sugerido con umbrales:

```powershell
powershell -File scripts/check-operational-thresholds.ps1 -ApiBase "http://localhost:5000" -Username "<admin>" -Secret "<password>" -MaxServerErrors 0 -MaxAvgDurationMs 2000 -MaxDurationMs 8000 -MaxProcessingBacklog 50
```

## 4) Respaldo (Backup) Antes de Release

Minimo requerido:
- [ ] Respaldo de `storage/` (documentos y artefactos locales).
- [ ] Respaldo de `logs/` si aplica cumplimiento/auditoria.
- [ ] Respaldo de variables de entorno seguras (sin exponer en repositorio).

Scripts operativos:

```powershell
powershell -File scripts/backup-operational.ps1 -IncludeLogs -IncludeEnv
powershell -File scripts/restore-operational.ps1 -BackupPath ".\backups\<timestamp>" -Overwrite
```

Ejemplo rapido (Windows):

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Compress-Archive -Path storage -DestinationPath "backups/storage-$stamp.zip"
Compress-Archive -Path logs -DestinationPath "backups/logs-$stamp.zip"
```

Cuando PostgreSQL este habilitado en produccion:
- [ ] Ejecutar `pg_dump` de la base productiva.
- [ ] Validar restauracion de prueba en entorno aislado.

## 5) Plan de Rollback

Preparacion:
- [ ] Tener identificada la version previa estable de frontend, backend y AI.
- [ ] Tener artefactos/versiones previas disponibles para redeploy.

Ejecucion rollback (si falla release):
1. Detener trafico o pausar operaciones de carga/proceso.
2. Redeploy de backend previo.
3. Redeploy de AI engine previo.
4. Redeploy de frontend previo.
5. Ejecutar smoke test y flujo minimo.
6. Comunicar incidente, causa, impacto y estado.

## 6) Criterio de Go/No-Go

Go:
- Todos los checks de secciones 1-5 en verde.

No-Go:
- Fallo en seguridad, vulnerabilidades activas criticas/altas, smoke fallando o falta de backup/rollback verificado.
