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


class EmailRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_url: str
    status: str
    markdown: Optional[str] = None
    search_text: Optional[str] = None
    classification: Optional[ClassificationResult] = None
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


class OCRFailed(Exception):
    pass
