# Contratos

## API C# → Python
**POST** `/process-document`

**multipart/form-data**
- file
- document_id
- source = "web"
- options (opcional JSON string)

Respuesta (JSON):
```json
{
  "document_id": "UUID",
  "status": "READY",
  "document_type": "INE",
  "confidence": 0.94,
  "fields": [
    {
      "key": "curp",
      "label": "CURP",
      "value": "PEPJ000101HDFRRN09",
      "confidence": 0.98,
      "valid": true,
      "validation_errors": [],
      "source": { "page": 1, "bbox": [120, 520, 430, 565] }
    }
  ],
  "warnings": [],
  "errors": [],
  "meta": {
    "pages_processed": 1,
    "ocr_engine": "paddleocr",
    "pipeline_version": "1.0.0",
    "model_version": "clf-v1.0.0",
    "processing_ms": 1840
  }
}
```

## Angular → C#
- **POST** `/api/auth/login`
- **POST** `/api/documents/upload`
- **GET** `/api/documents`
- **GET** `/api/documents/{id}`
- **GET** `/api/documents/{id}/file`
- **POST** `/api/documents/{id}/process`
- **PUT** `/api/documents/{id}/fields`
- **GET** `/api/documents/{id}/logs`
- **GET** `/api/system/info`
- **GET** `/api/system/metrics`

## Base de datos (PostgreSQL)
Se incluyen las tablas `documents`, `document_fields`, `processing_logs` y `model_versions`.
