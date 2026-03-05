import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.core.config import settings

# ---------------------------------------------------------------------------
# Correlation ID — ContextVar propagado por todo el ciclo de vida del request
# ---------------------------------------------------------------------------
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        corr_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        token = correlation_id_var.set(corr_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Correlation-Id"] = corr_id
        return response


class CorrelationIdFilter(logging.Filter):
    """Añade correlation_id a cada log record para incluirlo en el formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get("-")
        return True


def _configure_logging() -> None:
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    handler.addFilter(CorrelationIdFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_logging()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
_is_prod = settings.app_env in {"production", "prod"}
app = FastAPI(
    title="IA Engine",
    version="1.0.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS — permite al backend llamar al AI engine desde otros origenes
# ---------------------------------------------------------------------------
_cors_origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ---------------------------------------------------------------------------
# Rate-limiting simple (in-memory, por IP)
# ---------------------------------------------------------------------------
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = int(settings.rate_limit_max)  # max requests per window
_RATE_LIMIT_WINDOW = int(settings.rate_limit_window_seconds)  # seconds
_RATE_LIMIT_EVICT_INTERVAL = 300  # evict stale IPs every 5 min
_rate_limit_last_evict: float = 0.0


def _evict_stale_ips() -> None:
    """Remove IP entries with no recent hits to prevent memory leak."""
    global _rate_limit_last_evict
    now = time.time()
    if now - _rate_limit_last_evict < _RATE_LIMIT_EVICT_INTERVAL:
        return
    _rate_limit_last_evict = now
    stale = [ip for ip, hits in _rate_limit_store.items() if not hits or (now - hits[-1]) > _RATE_LIMIT_WINDOW]
    for ip in stale:
        _rate_limit_store.pop(ip, None)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        _evict_stale_ips()
        hits = _rate_limit_store.get(client_ip, [])
        hits = [t for t in hits if now - t < _RATE_LIMIT_WINDOW]
        if len(hits) >= _RATE_LIMIT_MAX:
            return Response(content='{"detail":"Too many requests"}', status_code=429, media_type="application/json")
        hits.append(now)
        _rate_limit_store[client_ip] = hits
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# ---------------------------------------------------------------------------
# Global exception handler — never leak stack traces to clients
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return Response(
        content='{"detail":"Internal server error"}',
        status_code=500,
        media_type="application/json",
    )


@app.on_event("startup")
async def validate_runtime_security():
    if settings.app_env in {"production", "prod"}:
        api_key = (settings.api_key or "").strip()
        weak = (not api_key) or ("CHANGE_ME" in api_key.upper()) or (len(api_key) < 24)
        if weak:
            raise RuntimeError("API_KEY insegura o no definida para APP_ENV=production.")
    elif not (settings.api_key or "").strip():
        logger.warning("API_KEY is empty — all endpoints are unprotected. Set API_KEY env var.")


@app.on_event("startup")
async def _preload_ocr_models():
    """Pre-load OCR models in background so first request is fast."""
    import asyncio
    async def _warm():
        try:
            from app.pipelines.ocr import warm_up
            await asyncio.to_thread(warm_up)
        except Exception:
            logger.warning("OCR warm-up failed, will retry on first request", exc_info=True)
    asyncio.create_task(_warm())


app.include_router(router)
