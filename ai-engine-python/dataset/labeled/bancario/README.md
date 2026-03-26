# labeled/bancario — Etiquetas esperadas para Documentos Bancarios

## Formato

```json
{
  "filename": "bancario_001.pdf",
  "document_type": "DATOS_BANCARIOS",
  "expected_fields": {
    "clabe":       "002010012345678901",
    "cuenta":      "0123456789",
    "banco":       "BBVA BANCOMER",
    "titular":     "JUAN PEREZ GARCIA",
    "rfc":         "PEGJ900101ABC",
    "fecha_corte": "28/02/2026",
    "periodo":     "01/02/2026 al 28/02/2026"
  }
}
```

## Campos obligatorios para evaluación

| Campo | Descripción |
|---|---|
| `clabe` | CLABE interbancaria de 18 dígitos |
| `banco` | Nombre de la institución bancaria |
| `titular` | Nombre del titular de la cuenta |
