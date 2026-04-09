# Load Testing — AI Engine

Pruebas de carga con [Locust](https://locust.io/) contra el AI Engine Python.

## Requisitos

```bash
pip install locust
```

## PDF de muestra

Coloca un PDF representativo en `tests/load/sample.pdf`.
Sin él, el test usa un PDF mínimo sintético (funcional pero no realista).

```bash
# Ejemplo: copiar cualquier PDF de prueba existente
cp ai-engine-python/tests/fixtures/algún_documento.pdf tests/load/sample.pdf
```

## Ejecución

### Interfaz web (interactivo)

```bash
LOAD_API_KEY=tu_api_key \
locust -f tests/load/locustfile.py --host http://localhost:8000
# Abre http://localhost:8089
```

### Headless (CI/CD)

```bash
LOAD_API_KEY=tu_api_key \
locust -f tests/load/locustfile.py \
  --host http://localhost:8000 \
  --headless -u 10 -r 2 --run-time 60s \
  --csv=reports/load
```

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `LOAD_API_KEY` | Valor de `X-Api-Key` | vacío (sin auth) |
| `LOAD_PDF_PATH` | Ruta al PDF de prueba | `tests/load/sample.pdf` |

## Perfiles de usuarios

| Perfil | Comportamiento | Peso |
|--------|---------------|------|
| `LightUser` | Mayormente health checks, pocos uploads | 3 |
| `HeavyUser` | Uploads continuos de documentos | 1 |

## Interpretación de resultados

- **RPS objetivo**: ≥ 5 req/s en `/health`, ≥ 0.5 req/s en `/process`
- **P95 latencia `/process`**: < 10s (documentos simples), < 30s (OCR pesado)
- **Tasa de error**: < 1% excluyendo 429 (rate limit esperado bajo carga)
