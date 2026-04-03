"""
conftest.py — fixtures globales para el suite de tests del AI Engine.

Configura variables de entorno mínimas antes de que se importen los módulos
de la app, garantizando que los tests corran sin un .env real.
"""

import os
import pytest

# ── Variables de entorno mínimas para que la app arranque en tests ────────────
# Se establecen antes de cualquier import de app.* para evitar errores de
# configuración en Settings (pydantic-settings lee los valores en el __init__).
_TEST_ENV_DEFAULTS = {
    "APP_ENV": "test",
    "API_KEY": "test-api-key-for-pytest-only",
    "CORS_ORIGINS": "http://localhost",
    "RATE_LIMIT_MAX": "9999",
    "RATE_LIMIT_WINDOW_SECONDS": "60",
    "AUDIT_BASE_PATH": "/tmp/ilcdia-test-storage",
    "LLM_FALLBACK_ENABLED": "false",
    "ANTHROPIC_API_KEY": "",
    "ENFORCE_PYTHON_RUNTIME": "false",
    "REQUIRE_OCR_BACKEND": "false",
}

for _key, _val in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _val)


# ── Fixtures disponibles para todos los módulos de tests ─────────────────────

@pytest.fixture(scope="session")
def test_storage_dir(tmp_path_factory):
    """Directorio temporal de almacenamiento para tests de sesión."""
    d = tmp_path_factory.mktemp("ilcdia-storage")
    os.environ["AUDIT_BASE_PATH"] = str(d)
    return d


@pytest.fixture(scope="session")
def fixtures_dir():
    """Ruta al directorio de fixtures de tests."""
    return os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_pdf_path(fixtures_dir):
    """Retorna la ruta a un PDF de muestra si existe, None si no."""
    path = os.path.join(fixtures_dir, "sample.pdf")
    return path if os.path.exists(path) else None


@pytest.fixture(scope="session")
def app_settings():
    """Instancia de Settings de la app para uso en tests."""
    from app.core.config import settings
    return settings
