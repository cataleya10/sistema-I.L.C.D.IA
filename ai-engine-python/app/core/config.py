from pydantic import BaseModel
import os

class Settings(BaseModel):
    pipeline_version: str = os.getenv("PIPELINE_VERSION", "1.0.0")
    model_version: str = os.getenv("MODEL_VERSION", "clf-v1.0.0")
    api_key: str | None = os.getenv("API_KEY")
    max_pages: int = int(os.getenv("MAX_PAGES", "10"))

settings = Settings()
