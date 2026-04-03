from pydantic import BaseModel
import os


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv_upper(name: str, default: str) -> list[str]:
    value = os.getenv(name, default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


class Settings(BaseModel):
    pipeline_version: str = os.getenv("PIPELINE_VERSION", "1.0.0")
    model_version: str = os.getenv("MODEL_VERSION", "clf-v1.0.0")
    api_key: str | None = os.getenv("API_KEY")
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    max_pages: int = int(os.getenv("MAX_PAGES", "100"))
    pdf_render_dpi: int = int(os.getenv("PDF_RENDER_DPI", "200"))
    min_text_layer_chars: int = int(os.getenv("MIN_TEXT_LAYER_CHARS", "180"))
    min_text_layer_words: int = int(os.getenv("MIN_TEXT_LAYER_WORDS", "25"))
    enable_text_layer_short_circuit: bool = _env_bool("ENABLE_TEXT_LAYER_SHORT_CIRCUIT", True)
    text_layer_fastpath_types: list[str] = _env_csv_upper(
        "TEXT_LAYER_FASTPATH_TYPES",
        "INE,CURP,ACTA_NACIMIENTO,COMPROBANTE_DOMICILIO,NSS,DATOS_BANCARIOS,FACTURA,NOMINA,CONSTANCIA_SITUACION_FISCAL",
    )
    llm_fallback_enabled: bool = _env_bool("LLM_FALLBACK_ENABLED", False)
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    cors_origins: str = os.getenv("CORS_ORIGINS", "")
    rate_limit_max: int = int(os.getenv("RATE_LIMIT_MAX", "120"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    payroll_strict_mode: bool = _env_bool("PAYROLL_STRICT_MODE", True)
    payroll_strict_min_rows: int = int(os.getenv("PAYROLL_STRICT_MIN_ROWS", "5"))
    payroll_strict_min_fill_rate: float = _env_float("PAYROLL_STRICT_MIN_FILL_RATE", 0.90)
    payroll_strict_max_dominant_surname_ratio: float = _env_float(
        "PAYROLL_STRICT_MAX_DOMINANT_SURNAME_RATIO", 0.55
    )
    enforce_python_runtime: bool = _env_bool("ENFORCE_PYTHON_RUNTIME", True)
    required_python_min: str = os.getenv("REQUIRED_PYTHON_MIN", "3.12")
    required_python_max_exclusive: str = os.getenv("REQUIRED_PYTHON_MAX_EXCLUSIVE", "3.13")
    require_ocr_backend: bool = _env_bool("REQUIRE_OCR_BACKEND", True)
    acta_sanity_guards_enabled: bool = _env_bool("ACTA_SANITY_GUARDS_ENABLED", True)
    # Ruta base permitida para el endpoint /diagnostics/audit-folder.
    # Peticiones con folder_path fuera de este directorio son rechazadas.
    audit_base_path: str = os.getenv("AUDIT_BASE_PATH", "storage")

settings = Settings()
