# Reglas OCR Por Campo

Guia rapida de normalizacion OCR en el pipeline de extraccion.

## Ubicacion principal
- Archivo: `ai-engine-python/app/pipelines/extract.py`
- Estrategia central: `FIELD_VALUE_NORMALIZERS`
- Dispatcher: `_normalize_value_for_key(key, value)`

## Campos con reglas especiales
- `cp`
  - Funcion: `_normalize_cp_value`
  - Objetivo: corregir confusiones `O/I/L` y forzar formato de 5 digitos.
- `folio`
  - Funcion: `_normalize_folio_value`
  - Objetivo: aceptar ruido OCR sin tomar texto no numerico como folio.
- `seccion`
  - Funcion: `_normalize_seccion_value`
  - Objetivo: corregir `SECCI0N`, limpiar ruido y remover ceros lideres cuando aplica.
- `numero_acta`
  - Funcion: `_normalize_numero_acta_value`
  - Objetivo: priorizar valor numerico limpio; fallback alfanumerico cuando sea necesario.
- `numero_certificado`
  - Funcion: `_normalize_numero_certificado_value`
  - Objetivo: normalizar secuencias largas con ruido OCR.
- `identificador_electronico`
  - Funcion: `_normalize_identificador_electronico_value`
  - Objetivo: conservar identificador alfanumerico limpio en mayusculas.
- `referencia`
  - Funcion: `_normalize_reference_value`
  - Objetivo: preferir referencia numerica (10-30), con fallback alfanumerico controlado.

## Principio de uso
- No normalizar cada campo con logica ad-hoc.
- Para campos de la tabla anterior, usar siempre:
  - `_normalize_value_for_key("<campo>", valor)`

## Pruebas de regresion
- Archivo: `ai-engine-python/tests/test_extract.py`
- Cobertura relevante:
  - `cp` con ruido OCR.
  - `folio` con ruido OCR.
  - `seccion` con `SECCI0N`.
  - `referencia` con ruido OCR.
  - `numero_acta`, `numero_certificado`, `identificador_electronico` en `ACTA_NACIMIENTO`.

## Comando de verificacion
```powershell
cd ai-engine-python
.\.venv312\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
