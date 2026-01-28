# IA Engine (FastAPI)

Servicio de OCR + clasificación + extracción.

## Ejecutar
```
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Notas
- PaddleOCR inicializado en `app/pipelines/ocr.py`.
- Extractores y validadores en `app/pipelines` y `app/utils`.

## Variables de entorno
- `PIPELINE_VERSION` (default: 1.0.0)
- `MODEL_VERSION` (default: clf-v1.0.0)
