# Sistema I.L.C.D.IA

Sistema web empresarial para carga, clasificación y extracción de documentos oficiales con IA.

## Estructura
- frontend-angular/web (Angular 20)
- backend-dotnet/src (API .NET 8 por capas)
- ai-engine-python/app (FastAPI + PaddleOCR)

## Estado actual
- MVP funcional sin base de datos (se deja pendiente por solicitud).
- Autenticación JWT con login.
- Motor IA con OCR, clasificación y extracción por tipo.

## Requisitos
- Node 24.11.0 / npm 11.6.1
- .NET 8 SDK
- Python 3.11+

## Arranque rápido (sin BD)
1) IA Engine
- Instalar dependencias: `pip install -r ai-engine-python/requirements.txt`
- Ejecutar: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

2) Backend API
- Ejecutar: `dotnet run --project backend-dotnet/src/Api`

3) Frontend
- Ejecutar: `npm install` en `frontend-angular/web`
- Ejecutar: `npm start`

## Credenciales de prueba
- admin / Admin123!
- analyst / Analyst123!

## Contratos
Ver [docs/contracts.md](docs/contracts.md).
