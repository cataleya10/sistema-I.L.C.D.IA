# Improvement Roadmap (Corto Plazo)

Roadmap tecnico priorizado para evolucionar el sistema manteniendo continuidad operativa.

## P0 - Estabilidad y Operacion (1-2 semanas)

- Unificar arranque con un solo runner reproducible por entorno (evitar procesos huérfanos).
- Endurecer health checks por servicio con timeouts y reintentos controlados.
- Cerrar brecha de configuracion runtime (`localhost` vs host real) con validacion previa al arranque.
- Ejecutar preflight automatizado en cada cambio de rama principal.

## P1 - Calidad OCR/Extraccion (2-4 semanas)

- Consolidar alias semanticos de campos criticos por tipo de documento.
- Mejorar contratos de validacion para actas/recibos con OCR ruidoso.
- Agregar dataset de regresion de documentos reales anonimizados.
- Medir precision por campo (coverage, precision, false review rate).

## P2 - Observabilidad y Soporte (2-4 semanas)

- Dashboard operativo con:
  - volumen por tipo de documento
  - tasa `READY` vs `NEEDS_REVIEW`
  - errores por etapa (preprocess/ocr/extract/validate)
- Correlation ID extremo a extremo (frontend -> backend -> ai engine).
- Alertas operativas para:
  - aumento de `NEEDS_REVIEW`
  - backlog de procesamiento
  - latencia p95

## P3 - Seguridad y Cumplimiento (3-6 semanas)

- Gestion de secretos fuera de `.env` local (vault o secret manager).
- Politica de rotacion de llaves JWT/API.
- Hardening de CORS por entorno y validacion de dominios permitidos.
- Auditoria de acceso y trazabilidad por usuario en correcciones manuales.

## P4 - Escalabilidad (4-8 semanas)

- Separar worker de procesamiento del API web para escalar por carga.
- Colas persistentes con reintento/backoff y dead-letter para fallos.
- Estrategia de almacenamiento para archivos grandes y retencion parametrizable.
- Pruebas de carga para definir capacidad por nodo.
