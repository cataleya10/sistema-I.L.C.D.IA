import logging
import uuid
from contextvars import ContextVar

from fastapi import FastAPI
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
app = FastAPI(title="IA Engine", version="1.0.0")

app.add_middleware(CorrelationIdMiddleware)


@app.on_event("startup")
async def validate_runtime_security():
    if settings.app_env in {"production", "prod"}:
        api_key = (settings.api_key or "").strip()
        weak = (not api_key) or ("CHANGE_ME" in api_key.upper()) or (len(api_key) < 24)
        if weak:
            raise RuntimeError("API_KEY insegura o no definida para APP_ENV=production.")


app.include_router(router)
