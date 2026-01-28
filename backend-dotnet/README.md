# Backend .NET 8

API por capas con autenticación JWT y endpoints de documentos.

## Ejecutar
```
dotnet run --project src/Api
```

## Configuración
- `appsettings.json` contiene JWT, Storage y SystemInfo.
- Base de datos pendiente.

## Endpoints
- `POST /api/auth/login`
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/documents/{id}`
- `GET /api/documents/{id}/file`
- `POST /api/documents/{id}/process`
- `PUT /api/documents/{id}/fields`
- `GET /api/documents/{id}/logs`
- `GET /api/system/info`
- `GET /api/system/metrics`
