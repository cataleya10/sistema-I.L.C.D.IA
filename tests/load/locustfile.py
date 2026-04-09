"""
Locust load test — AI Engine Python
====================================
Uso:
    # Con interfaz web (abre http://localhost:8089)
    locust -f tests/load/locustfile.py --host http://localhost:8000

    # Headless (CI/CD)
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
           --headless -u 10 -r 2 --run-time 60s \
           --csv=reports/load

Variables de entorno:
    LOAD_API_KEY    Valor de X-Api-Key (obligatorio si la API está protegida)
    LOAD_PDF_PATH   Ruta a un PDF de prueba (default: tests/load/sample.pdf)
"""

import io
import os
import pathlib
import random
from locust import HttpUser, TaskSet, task, between, events

_API_KEY = os.getenv("LOAD_API_KEY", "")
_PDF_PATH = pathlib.Path(os.getenv("LOAD_PDF_PATH", "tests/load/sample.pdf"))


def _headers(extra: dict | None = None) -> dict:
    h = {"X-Correlation-Id": f"locust-{random.randint(100000, 999999)}"}
    if _API_KEY:
        h["X-Api-Key"] = _API_KEY
    if extra:
        h.update(extra)
    return h


def _pdf_bytes() -> bytes:
    """Devuelve el contenido del PDF de prueba o un PDF mínimo si no existe."""
    if _PDF_PATH.exists():
        return _PDF_PATH.read_bytes()
    # PDF mínimo válido de 1 página en blanco (no necesita librerías externas)
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n"
        b"0000000058 00000 n\n0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )


# ── Task sets ─────────────────────────────────────────────────────────────────

class HealthTasks(TaskSet):
    """Sondeos de liveness — peso alto, coste bajo."""

    @task(10)
    def health(self):
        with self.client.get("/health", headers=_headers(), catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"health devolvió {r.status_code}")


class ProcessTasks(TaskSet):
    """Procesamiento de documentos — carga real."""

    @task(3)
    def process_document(self):
        pdf = _pdf_bytes()
        files = {"file": ("test.pdf", io.BytesIO(pdf), "application/pdf")}
        data = {"document_id": f"load-{random.randint(1, 9999)}"}
        with self.client.post(
            "/process",
            headers=_headers(),
            files=files,
            data=data,
            catch_response=True,
            name="/process [PDF]",
        ) as r:
            if r.status_code in (200, 422):
                # 422 = documento no reconocido, pero API está viva
                r.success()
            elif r.status_code == 429:
                r.success()  # rate-limit esperado bajo carga
            else:
                r.failure(f"process devolvió {r.status_code}: {r.text[:200]}")

    @task(1)
    def process_with_options(self):
        """Mismo endpoint con opciones JSON para ejercitar el parser."""
        pdf = _pdf_bytes()
        files = {"file": ("test.pdf", io.BytesIO(pdf), "application/pdf")}
        data = {
            "document_id": f"load-opt-{random.randint(1, 9999)}",
            "options": '{"force_ocr": false, "llm_fallback": false}',
        }
        with self.client.post(
            "/process",
            headers=_headers(),
            files=files,
            data=data,
            catch_response=True,
            name="/process [PDF+options]",
        ) as r:
            if r.status_code in (200, 422, 429):
                r.success()
            else:
                r.failure(f"process+options devolvió {r.status_code}")


class MixedTasks(TaskSet):
    """Mezcla realista: mayoría health, minoría proceso."""
    tasks = {HealthTasks: 5, ProcessTasks: 1}


# ── User profiles ─────────────────────────────────────────────────────────────

class LightUser(HttpUser):
    """Usuario liviano — sondeos frecuentes, pocos documentos."""
    tasks = [MixedTasks]
    wait_time = between(1, 3)
    weight = 3


class HeavyUser(HttpUser):
    """Usuario pesado — sube documentos continuamente."""
    tasks = [ProcessTasks]
    wait_time = between(5, 15)
    weight = 1


# ── Eventos ───────────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    if not _API_KEY:
        print(
            "\n[WARN] LOAD_API_KEY no definida — "
            "las peticiones se enviarán sin autenticación.\n"
        )
    if not _PDF_PATH.exists():
        print(
            f"\n[WARN] PDF de prueba no encontrado en {_PDF_PATH} — "
            "se usará un PDF mínimo sintético.\n"
        )
