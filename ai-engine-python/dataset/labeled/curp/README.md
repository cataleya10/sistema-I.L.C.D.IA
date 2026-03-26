# labeled/curp — Etiquetas esperadas para documentos CURP

## Formato

```json
{
  "filename": "curp_001.pdf",
  "document_type": "CURP",
  "expected_fields": {
    "curp":               "ABCD900101HDFXYZ01",
    "nombre":             "JUAN PEREZ GARCIA",
    "fecha_nacimiento":   "01/01/1990",
    "sexo":               "M",
    "entidad_nacimiento": "CIUDAD DE MEXICO"
  }
}
```

## Campos obligatorios para evaluación

| Campo | Descripción |
|---|---|
| `curp` | CURP de 18 caracteres |
| `nombre` | Nombre completo en mayúsculas |
| `fecha_nacimiento` | Formato DD/MM/YYYY |
| `sexo` | "M" o "F" |
| `entidad_nacimiento` | Nombre del estado de nacimiento |
