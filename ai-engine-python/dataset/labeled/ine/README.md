# labeled/ine — Etiquetas esperadas para documentos INE

Cada archivo JSON aquí corresponde a un PDF/imagen en `raw/ine/` con el mismo nombre base.

## Formato

```json
{
  "filename": "ine_001.pdf",
  "document_type": "INE",
  "expected_fields": {
    "curp":             "ABCD900101HDFXYZ01",
    "nombre":           "JUAN PEREZ GARCIA",
    "fecha_nacimiento": "01/01/1990",
    "sexo":             "M",
    "domicilio":        "CALLE 123, COL. CENTRO, CDMX",
    "clave_elector":    "PRGJN90010112H300",
    "seccion":          "1234",
    "vigencia":         "2030",
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
| `clave_elector` | 18 caracteres alfanuméricos |
