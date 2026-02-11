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
- Refresh tokens persistentes: se almacenan en `storage/refresh_tokens.json`.
- Limpieza de archivos: configurar `Storage__RetentionDays` (>0 habilita borrado automatico).

## Arranque rapido (sin BD)
1) IA Engine
- Instalar dependencias: `pip install -r ai-engine-python/requirements.txt`
- Ejecutar: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

2) Backend API
- Ejecutar: `dotnet run --project backend-dotnet/src/Api`

3) Frontend
- Ejecutar: `npm install` en `frontend-angular/web`
- Ejecutar: `npm start`

## Smoke test
- Ejecutar: `powershell -File scripts/smoke.ps1`

## Verificacion local
- Ejecutar: `powershell -File scripts/verify-all.ps1`
- Rapido (sin frontend tests): `powershell -File scripts/verify-all.ps1 -SkipFrontendTests`

## Flujo MVP (sin BD)
1) Cargar documento desde el frontend.
2) Procesar documento (la llamada espera la respuesta del motor IA).
3) Revisar y corregir campos si aplica.

## Credenciales de prueba
- admin / Admin123!
- analyst / Analyst123!

## Contratos
Ver [docs/contracts.md](docs/contracts.md).

## Reglas OCR
Ver [docs/ocr-field-normalization.md](docs/ocr-field-normalization.md).
