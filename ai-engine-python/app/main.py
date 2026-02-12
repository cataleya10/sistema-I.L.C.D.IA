from fastapi import FastAPI
from app.api.routes import router
from app.core.config import settings

app = FastAPI(title="IA Engine", version="1.0.0")


@app.on_event("startup")
async def validate_runtime_security():
    if settings.app_env in {"production", "prod"}:
        api_key = (settings.api_key or "").strip()
        weak = (not api_key) or ("CHANGE_ME" in api_key.upper()) or (len(api_key) < 24)
        if weak:
            raise RuntimeError("API_KEY insegura o no definida para APP_ENV=production.")


app.include_router(router)
