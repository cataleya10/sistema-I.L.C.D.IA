# Dataset de Entrenamiento

Estructura del dataset para entrenamiento y evaluación de extractores.

```
dataset/
├── raw/          ← Documentos originales sin procesar (PDF, imágenes)
│   ├── ine/
│   ├── curp/
│   ├── nomina/
│   └── bancario/
│
├── labeled/      ← Documentos con anotaciones esperadas en JSON
│   ├── ine/
│   ├── curp/
│   ├── nomina/
│   └── bancario/
│
├── corrected/    ← Documentos donde el extractor falló y se corrigió manualmente
│   ├── ine/
│   ├── curp/
│   ├── nomina/
│   └── bancario/
│
└── manifests/
    └── dataset_index.json   ← Índice de todos los documentos del dataset
```

## Cómo agregar documentos

1. Coloca el PDF o imagen en `raw/<tipo>/`
2. Crea el archivo de etiquetas en `labeled/<tipo>/` con el mismo nombre base + `.json`
3. Ejecuta `tools/prepare_training_data.py` para indexar el documento

## Formato de archivo de etiquetas (`labeled/<tipo>/<nombre>.json`)

```json
{
  "filename": "documento.pdf",
  "document_type": "INE",
  "expected_fields": {
    "curp": "ABCD900101HDFXYZ01",
    "nombre": "JUAN PEREZ GARCIA",
    "fecha_nacimiento": "01/01/1990",
    "sexo": "M",
    "clave_elector": "PRGJN90010112H300"
  }
}
```
