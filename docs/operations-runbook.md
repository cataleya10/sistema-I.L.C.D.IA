# Operations Runbook (Diario)

Guia corta para operar `Sistema I.L.C.D.IA` en entorno local/staging tecnico.

## 1) Arranque rapido

1. Cargar variables:
   - `. .\load-env.ps1`
2. Levantar stack:
   - `powershell -File start-all.ps1`
3. Verificar salud:
   - `http://localhost:5000/health`
   - `http://localhost:8000/docs`
   - Frontend en `http://localhost:<puerto>`

## 2) Verificacion operativa minima

1. Smoke:
   - `powershell -File scripts/smoke.ps1 -ApiBase "http://localhost:5000" -AiBase "http://localhost:8000"`
2. Umbrales:
   - `powershell -File scripts/check-operational-thresholds.ps1 -ApiBase "http://localhost:5000" -Username "<admin>" -Secret "<password>"`
3. Estado de documentos:
   - Revisar bandeja y confirmar que nuevos documentos terminan en `READY`.

## 3) Diagnostico rapido (si algo falla)

1. Revisar logs:
   - API: `backend-dotnet/src/Api/logs/api.log`
   - Stack: `logs/backend-api.log`, `logs/ai-engine.log`, `logs/frontend.log`
2. Errores frecuentes:
   - `401` en IA: `PythonAi__ApiKey` y `API_KEY` no coinciden.
   - `NEEDS_REVIEW` masivo: revisar cambios recientes en `extract.py`/validadores.
   - Frontend sin datos: validar `frontend-angular/web/public/app-config.js`.
3. Verificar backlog:
   - `scripts/check-operational-thresholds.ps1` y confirmar `processing_backlog=0`.

## 4) Recuperacion

1. Reinicio controlado:
   - `powershell -File stop-all.ps1`
   - `powershell -File start-all.ps1`
2. Modo protegido:
   - `powershell -File scripts/guard-mode.ps1 -Username "<usuario>" -Secret "<password>"`
3. Si persiste:
   - Restaurar respaldo operativo:
     - `powershell -File scripts/restore-operational.ps1 -BackupPath ".\backups\<timestamp>" -Overwrite`

## 5) Backup diario recomendado

1. Ejecutar:
   - `powershell -File scripts/backup-operational.ps1 -IncludeLogs -IncludeEnv`
2. Validar carpeta en `backups/<timestamp>`.

## 6) Criterio de escalamiento

Escalar a soporte tecnico cuando ocurra cualquiera de estos:
1. Error 5xx sostenido.
2. `processing_backlog` creciendo por mas de 10 minutos.
3. Caida repetida de IA o API.
4. Mas de 20% de documentos nuevos en `NEEDS_REVIEW` sin causa de calidad de archivo.
