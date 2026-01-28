from pydantic import BaseModel
import os

class Settings(BaseModel):
    pipeline_version: str = os.getenv("PIPELINE_VERSION", "1.0.0")
    model_version: str = os.getenv("MODEL_VERSION", "clf-v1.0.0")

settings = Settings()
