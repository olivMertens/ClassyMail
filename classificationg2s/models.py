from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class ClassificationIntent(BaseModel):
    intent: str
    confidence: float
    justification: Optional[str] = None


class ClassificationResult(BaseModel):
    detected_intents: List[ClassificationIntent]
    global_complexity: Optional[str] = None
    needs_review: bool = False
    raw_response: Optional[dict] = None


class HistoryEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_intents: List[ClassificationIntent] = []
    previous_status: Optional[str] = None
    updated_by: Optional[str] = "user"
    correction_reason: Optional[str] = None
    llm_feedback: Optional[str] = None


class EmailRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_url: str
    status: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    processing_time_ms: Optional[float] = None
    markdown: Optional[str] = None
    search_text: Optional[str] = None
    vector: Optional[List[float]] = None
    classification: Optional[ClassificationResult] = None
    classification_history: List[HistoryEntry] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    error_stage: Optional[str] = None
    processing_log: Optional[list[dict]] = None
    usage: Optional[dict] = None


class EmailListResponse(BaseModel):
    items: List[EmailRecord]
    total: int
    review_required: int
    processed: int
    finetune_reviewed_ready: int = 0
    finetune_min_required: int = 50
    finetune_ready: bool = False
    continuation_token: Optional[str] = None
    average_confidence: Optional[float] = 0.0


class OCRFailed(Exception):
    def __init__(self, message: str, *, processing_log: list[dict] | None = None, retryable: bool = False):
        super().__init__(message)
        self.processing_log = processing_log
        self.retryable = retryable
