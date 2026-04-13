"""
tests/test_api_routes.py — HTTP-level tests for all API endpoints.

Uses httpx.AsyncClient + ASGITransport to exercise the real FastAPI stack:
authentication, middleware, request validation, serialisation, and status codes.
Service-layer functions are mocked to isolate the HTTP/routing layer.
"""

import pytest
from unittest.mock import patch, AsyncMock

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.schemas.process import (
    ProcessResponse,
    CampoExtraido,
    TablaExtraida,
    MetadataDocumento,
    ValidationSummary,
)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "http://test"
API_KEY = "test-api-key-for-pytest-only"
AUTH = {"X-Api-Key": API_KEY}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_process_response(
    *,
    doc_type: str = "INE",
    requires_review: bool = False,
    campos: list | None = None,
    tablas: list | None = None,
) -> ProcessResponse:
    """Construye un ProcessResponse realista para mocks del servicio."""
    return ProcessResponse(
        document_id="doc-test",
        tipo_documento=doc_type,
        success=not requires_review,
        message="Documento procesado correctamente" if not requires_review else "Requiere revisión.",
        confidence_global=0.92,
        campos=campos or [
            CampoExtraido(key="curp", label="CURP", value="AACD900101HDFRRL09",
                          confidence=0.97, is_critical=True, is_valid=True),
            CampoExtraido(key="nombre", label="Nombre", value="JUAN PEREZ",
                          confidence=0.90, is_critical=True, is_valid=True),
        ],
        tablas=tablas or [],
        metadata=MetadataDocumento(
            filename="doc.pdf", pages=1, source="web",
            processing_time_ms=1200, ocr_engine="paddleocr",
        ),
        validation_summary=ValidationSummary(
            coverage=1.0,
            critical_coverage=1.0,
            requires_review=requires_review,
        ),
    )


def _post_file(client: AsyncClient, path: str, *, data: dict, headers: dict | None = None):
    """Shortcut: POST multipart con un PDF fake."""
    return client.post(
        path,
        headers=headers or AUTH,
        data=data,
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )


# ── Fixture: httpx client sobre la app real ───────────────────────────────────

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


# ═════════════════════════════════════════════════════════════════════════════
# Health (sin autenticación)
# ═════════════════════════════════════════════════════════════════════════════

async def test_health_returns_200_without_auth(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


# ═════════════════════════════════════════════════════════════════════════════
# Autenticación — todos los endpoints protegidos devuelven 401
# ═════════════════════════════════════════════════════════════════════════════

async def test_process_document_requires_auth(client):
    resp = await client.post(
        "/process-document",
        data={"document_id": "d1", "source": "web"},
        files={"file": ("f.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 401


async def test_audit_folder_requires_auth(client):
    resp = await client.post("/diagnostics/audit-folder", json={"folder_path": "docs"})
    assert resp.status_code == 401


async def test_online_learning_stats_requires_auth(client):
    resp = await client.get("/online-learning/stats")
    assert resp.status_code == 401


async def test_metrics_requires_auth(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 401


async def test_invalid_api_key_returns_401(client):
    resp = await client.get("/online-learning/stats", headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# POST /process-document — contrato v2
# ═════════════════════════════════════════════════════════════════════════════

async def test_process_document_success_contract(client):
    """Respuesta exitosa contiene todas las claves del contrato v2."""
    mock_resp = _make_process_response()
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=mock_resp)):
        resp = await _post_file(client, "/process-document", data={"document_id": "doc-test", "source": "web"})

    assert resp.status_code == 200
    body = resp.json()
    # Claves obligatorias del contrato
    assert body["document_id"] == "doc-test"
    assert body["tipo_documento"] == "INE"
    assert body["success"] is True
    assert 0.0 <= body["confidence_global"] <= 1.0
    # Campos
    assert len(body["campos"]) == 2
    campo = body["campos"][0]
    assert "is_critical" in campo
    assert "is_valid" in campo
    assert isinstance(campo["confidence"], float)
    # Metadata
    meta = body["metadata"]
    assert isinstance(meta["filename"], str)
    assert isinstance(meta["pages"], int)
    assert isinstance(meta["processing_time_ms"], int)
    # Validation summary
    vs = body["validation_summary"]
    assert vs["score_decision"] in ("accepted", "review", "reprocess")
    assert isinstance(vs["coverage"], float)
    assert isinstance(vs["critical_coverage"], float)
    assert isinstance(vs["table_quality_score"], (int, float))


async def test_process_document_requires_review(client):
    mock_resp = _make_process_response(requires_review=True)
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=mock_resp)):
        resp = await _post_file(client, "/process-document", data={"document_id": "doc-r", "source": "web"})

    body = resp.json()
    assert body["success"] is False
    assert body["validation_summary"]["requires_review"] is True


async def test_process_document_error_response(client):
    error_resp = ProcessResponse(
        document_id="doc-err",
        tipo_documento="UNKNOWN",
        success=False,
        message="Tipo de documento no identificado.",
        error_code="DOCUMENT_TYPE_UNKNOWN",
        stage="classification",
        metadata=MetadataDocumento(filename="doc.pdf"),
        validation_summary=ValidationSummary(requires_review=True, score_decision="reprocess"),
    )
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=error_resp)):
        resp = await _post_file(client, "/process-document", data={"document_id": "doc-err", "source": "web"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == "DOCUMENT_TYPE_UNKNOWN"
    assert body["stage"] == "classification"
    assert body["validation_summary"]["score_decision"] == "reprocess"


async def test_process_document_table_not_found(client):
    error_resp = ProcessResponse(
        document_id="doc-t",
        tipo_documento="FACTURA",
        success=True,
        message="No se detectó tabla principal en el documento.",
        error_code="TABLE_NOT_FOUND",
        stage="table_extraction",
        metadata=MetadataDocumento(filename="doc.pdf"),
        validation_summary=ValidationSummary(requires_review=True, score_decision="review", table_quality_score=0.0),
    )
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=error_resp)):
        resp = await _post_file(client, "/process-document", data={"document_id": "doc-t", "source": "web"})

    body = resp.json()
    assert body["error_code"] == "TABLE_NOT_FOUND"
    assert body["validation_summary"]["requires_review"] is True
    assert body["validation_summary"]["table_quality_score"] == 0.0


async def test_process_document_with_tablas(client):
    tablas = [
        TablaExtraida(
            name="tabla_principal",
            headers_detected=["fecha", "importe"],
            rows=[],
            canonical_rows=[{"fecha": "2026-03-22", "importe": "1500.00"}],
        )
    ]
    mock_resp = _make_process_response(tablas=tablas)
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=mock_resp)):
        resp = await _post_file(client, "/process-document", data={"document_id": "doc-t", "source": "web"})

    body = resp.json()
    assert len(body["tablas"]) == 1
    assert body["tablas"][0]["name"] == "tabla_principal"
    assert "fecha" in body["tablas"][0]["headers_detected"]
    assert len(body["tablas"][0]["canonical_rows"]) == 1


# ── Validaciones de entrada ──────────────────────────────────────────────────

async def test_process_document_invalid_document_id_returns_422(client):
    resp = await _post_file(
        client, "/process-document",
        data={"document_id": "id con espacios!!", "source": "web"},
    )
    assert resp.status_code == 422


async def test_process_document_invalid_options_json_returns_422(client):
    resp = await _post_file(
        client, "/process-document",
        data={"document_id": "doc-ok", "source": "web", "options": "not json"},
    )
    assert resp.status_code == 422


async def test_process_document_valid_options_json(client):
    mock_resp = _make_process_response()
    with patch("app.api.routes.process_document", new=AsyncMock(return_value=mock_resp)):
        resp = await _post_file(
            client, "/process-document",
            data={"document_id": "doc-ok", "source": "web", "options": '{"force_type":"INE"}'},
        )
    assert resp.status_code == 200


async def test_process_document_options_too_long_returns_422(client):
    resp = await _post_file(
        client, "/process-document",
        data={"document_id": "doc-ok", "source": "web", "options": '{"x":"' + "A" * 2100 + '"}'},
    )
    assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# POST /diagnostics/audit-folder
# ═════════════════════════════════════════════════════════════════════════════

async def test_audit_folder_success(client, tmp_path, monkeypatch):
    target = tmp_path / "docs"
    target.mkdir()
    monkeypatch.setattr(settings, "audit_base_path", str(tmp_path))

    expected = {
        "folder_path": "docs",
        "recurse": True,
        "limit": 25,
        "issues_only": False,
        "matched_files": 3,
        "processed_files": 3,
        "documents_returned": 3,
        "clean_count": 2,
        "issue_count": 1,
        "error_count": 0,
        "hard_fail_count": 0,
        "non_factura_count": 0,
        "document_type_counts": {"FACTURA": 3},
        "documents": [],
    }
    with patch("app.api.routes.run_audit_folder", new=AsyncMock(return_value=expected)) as audit_mock:
        resp = await client.post(
            "/diagnostics/audit-folder",
            headers=AUTH,
            json={"folder_path": "docs", "recurse": True, "limit": 25, "issues_only": False},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_files"] == 3
    assert body["clean_count"] == 2
    audit_mock.assert_called_once_with(str(target), recurse=True, limit=25, issues_only=False)


async def test_audit_folder_path_traversal_returns_403(client):
    resp = await client.post(
        "/diagnostics/audit-folder",
        headers=AUTH,
        json={"folder_path": "../../../etc/passwd"},
    )
    assert resp.status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# GET /online-learning/stats
# ═════════════════════════════════════════════════════════════════════════════

async def test_online_learning_stats_success(client):
    expected = {
        "totals": {"attempted": 7, "trained": 5, "skipped": 2},
        "recent_events": [],
    }
    with patch("app.api.routes.get_online_learning_stats", return_value=expected) as mock:
        resp = await client.get("/online-learning/stats", headers=AUTH, params={"recent": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["attempted"] == 7
    mock.assert_called_once_with(recent=3)


# ═════════════════════════════════════════════════════════════════════════════
# POST /online-learning/feedback
# ═════════════════════════════════════════════════════════════════════════════

async def test_online_learning_feedback_success(client):
    expected = {"accepted": True, "labels": 2}
    with patch("app.api.routes.record_feedback_document", return_value=expected) as mock:
        resp = await client.post(
            "/online-learning/feedback",
            headers=AUTH,
            json={
                "document_id": "doc-1",
                "document_type": "CURP",
                "ocr_text": "CONSTANCIA CURP",
                "corrected_fields": [
                    {"key": "curp", "value": "AAAA000101HDFRRL00"},
                    {"key": "nombre", "value": "JUAN PEREZ"},
                ],
            },
        )

    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    mock.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# POST /online-learning/retrain
# ═════════════════════════════════════════════════════════════════════════════

async def test_online_learning_retrain_success(client):
    expected = {"promoted": True, "decision_reasons": []}
    with patch("app.api.routes.run_feedback_retraining", return_value=expected) as mock:
        resp = await client.post(
            "/online-learning/retrain",
            headers=AUTH,
            json={
                "min_feedback_samples": 10,
                "validation_ratio": 0.2,
                "min_doc_accuracy": 0.9,
                "min_validation_docs": 3,
                "max_accuracy_drop": 0.02,
                "promote": True,
            },
        )

    assert resp.status_code == 200
    assert resp.json()["promoted"] is True
    mock.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# GET /metrics
# ═════════════════════════════════════════════════════════════════════════════

async def test_metrics_success(client):
    expected = {"precision": 0.95, "recall": 0.90}
    with patch("app.api.routes.get_precision_metrics", return_value=expected):
        resp = await client.get("/metrics", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["precision"] == 0.95
