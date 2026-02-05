from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict

from pydantic import BaseModel, Field


class ClassificationIntent(BaseModel):
    intent: str
    confidence: float
    justification: Optional[str] = None


class ClassificationResult(BaseModel):
    detected_intents: List[ClassificationIntent]
    global_complexity: Optional[str] = None
    needs_review: bool = False
    classification_reason: Optional[str] = None  # Explanation when no category found
    raw_response: Optional[dict] = None
    detected_pii: Optional[dict] = None  # PII detection results from preprocessing


class ComparisonResult(BaseModel):
    """Stores multi-model adversarial comparison results"""
    model_config = {'protected_namespaces': ()}
    model_results: Dict[str, ClassificationResult] = Field(default_factory=dict)
    confidence_delta: Optional[float] = None  # Absolute difference in top intent confidence
    agreement: bool = False  # True if all/both models detected same top intent
    executed_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: str = "sync"  # "sync" or "async"
    processing_time_ms: Optional[float] = None
    # Legacy fields for backward compatibility
    phi4: Optional[ClassificationResult] = None
    gpt4o_mini: Optional[ClassificationResult] = None


class HistoryEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_intents: List[ClassificationIntent] = []
    previous_status: Optional[str] = None
    updated_by: Optional[str] = "user"
    correction_reason: Optional[str] = None
    llm_feedback: Optional[str] = None


class BusinessEntities(BaseModel):
    """Broad entity extraction (Forgiving Schema)"""
    people: List[str] = Field(default_factory=list)
    organizations: List[str] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    monetary_amounts: List[str] = Field(default_factory=list)
    reference_numbers: List[str] = Field(default_factory=list, description="IDs, Policy #, Invoice #, etc.")


class EmailRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_url: str
    file_url_proxy: Optional[str] = None  # Managed Identity proxy endpoint
    file_url_sas: Optional[str] = None    # Legacy SAS URL (deprecated)
    status: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    processing_time_ms: Optional[float] = None
    markdown: Optional[str] = None
    search_text: Optional[str] = None
    vector: Optional[List[float]] = None
    chunks: Optional[List[dict]] = None
    classification: Optional[ClassificationResult] = None
    entities: Optional[BusinessEntities] = None  # Auto-extracted entities
    pii_detected: Optional[bool] = False  # Whether PII was found
    pii_data: Optional[dict] = None  # Structured PII extraction (for GDPR audits)
    preprocessing_metadata: Optional[dict] = None  # Preprocessing info (subject, conversation extraction)
    comparison_results: List[ComparisonResult] = Field(default_factory=list)  # Adversarial model comparison (dual-model results)
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
