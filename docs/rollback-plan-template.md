# Rollback Plan Template

Fecha: `YYYY-MM-DD`  
Release objetivo: `<tag/folio-release>`  
Responsable: `<owner>`

## 1) Versiones Previas Estables

1. Frontend:
   - Version/tag: `<frontend-tag>`
   - Artefacto: `<url-registry-o-paquete>`
2. Backend:
   - Version/tag: `<backend-tag>`
   - Artefacto: `<url-registry-o-paquete>`
3. AI Engine:
   - Version/tag: `<ai-tag>`
   - Artefacto: `<url-registry-o-paquete>`

## 2) Criterio de Activacion de Rollback

1. Error funcional critico en flujo principal.
2. Error 5xx sostenido por encima del umbral.
3. Degradacion severa de latencia o backlog.
4. Incidente de seguridad o integridad de datos.

## 3) Procedimiento Operativo

1. Pausar trafico y/o procesos de carga.
2. Redeploy backend previo.
3. Redeploy AI engine previo.
4. Redeploy frontend previo.
5. Ejecutar smoke post-rollback:
   - `powershell -File scripts/smoke.ps1 -ApiBase "<api>" -AiBase "<ai>" -Username "<user>" -Password "<pass>"`
6. Verificar metricas y backlog.
7. Comunicar incidente y estado.

## 4) Verificacion Post-Rollback

1. `GET /health` responde 200.
2. Login responde correctamente.
3. Flujo minimo funcional (upload -> process -> consulta status).
4. Exportes funcionales.
5. Errores/latencia dentro de umbral.

## 5) Evidencia

1. Hora inicio rollback: `<hh:mm:ss>`
2. Hora fin rollback: `<hh:mm:ss>`
3. Comandos ejecutados: `<lista>`
4. Resultado final: `<OK/FAIL>`

