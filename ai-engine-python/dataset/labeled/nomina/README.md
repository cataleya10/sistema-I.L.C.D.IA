# labeled/nomina — Etiquetas esperadas para Recibos de Nómina

## Formato

```json
{
  "filename": "nomina_001.pdf",
  "document_type": "NOMINA",
  "expected_fields": {
    "nombre":              "JUAN PEREZ GARCIA",
    "rfc":                 "PEGJ900101ABC",
    "nss":                 "12345678901",
    "curp":                "PEGJ900101HDFXYZ01",
    "empresa":             "EMPRESA SA DE CV",
    "periodo":             "01/03/2026 al 15/03/2026",
    "fecha_pago":          "15/03/2026",
    "total_percepciones":  "15000.00",
    "total_deducciones":   "3000.00",
    "neto_pagar":          "12000.00"
  }
}
```

## Campos obligatorios para evaluación

| Campo | Descripción |
|---|---|
| `nombre` | Nombre del empleado |
| `nss` | NSS de 11 dígitos |
| `periodo` | Periodo de pago |
| `neto_pagar` | Monto neto a pagar |
