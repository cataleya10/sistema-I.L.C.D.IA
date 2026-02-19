from pydantic import BaseModel, Field
from typing import Any


class FeedbackField(BaseModel):
    key: str
    value: str
    confidence: float | None = None


class OnlineLearningFeedbackRequest(BaseModel):
    document_id: str
    document_type: str
    ocr_text: str
    corrected_fields: list[FeedbackField] = Field(default_factory=list)
    extracted_fields: list[dict[str, Any]] = Field(default_factory=list)
    reviewer: str | None = None
    source: str = "human_review"


class OnlineLearningRetrainRequest(BaseModel):
    min_feedback_samples: int = Field(default=20, ge=1)
    validation_ratio: float = Field(default=0.2, gt=0, lt=0.5)
    min_doc_accuracy: float = Field(default=0.9, ge=0, le=1)
    min_validation_docs: int = Field(default=5, ge=1)
    max_accuracy_drop: float = Field(default=0.02, ge=0, le=0.5)
    promote: bool = True
