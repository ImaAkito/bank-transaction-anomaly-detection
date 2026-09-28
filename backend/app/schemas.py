"""Pydantic-схемы REST API."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
Status = Literal["normal", "needs_review", "reviewed_normal", "reviewed_suspicious"]
ReviewStatus = Literal["needs_review", "reviewed_normal", "reviewed_suspicious"]


class TransactionIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=8)
    category: str = Field(min_length=1, max_length=64)
    channel: str = Field(default="unknown", max_length=32)
    recipient_id: str | None = Field(default=None, max_length=128)
    recipient_category: str | None = Field(default=None, max_length=64)
    extra: dict[str, Any] = Field(default_factory=dict)
    # Только для демонстрации: истинная метка симулятора. В модель не передаётся.
    simulation_label: bool | None = None
    simulation_anomaly_type: str | None = Field(default=None, max_length=64)


class Reason(BaseModel):
    code: str
    type: str
    severity: float
    value: Any = None
    text: str


class Factor(BaseModel):
    feature: str
    label: str
    value: float
    contribution: float
    direction: Literal["increases", "decreases"]


class AnalysisOut(BaseModel):
    anomaly_score: float
    risk_level: RiskLevel
    status: Status
    summary: str
    deviation_types: list[str]
    reasons: list[Reason]
    factors: list[Factor]
    features: dict[str, float]
    model_version: str
    model_kind: str
    latency_ms: float
    profile_updated: bool
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    created_at: datetime


class TransactionOut(BaseModel):
    transaction_id: str
    client_id: str
    timestamp: datetime
    amount: float
    currency: str
    amount_base: float
    category: str
    channel: str
    recipient_id: str | None
    recipient_category: str | None
    extra: dict[str, Any] | None
    simulation_label: bool | None
    simulation_anomaly_type: str | None
    received_at: datetime
    analysis: AnalysisOut


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class QueuedOut(BaseModel):
    status: Literal["queued"] = "queued"
    transaction_id: str
    queue_depth: int


class ReviewIn(BaseModel):
    status: ReviewStatus
    reviewer: str = Field(default="analyst", max_length=128)
    comment: str | None = Field(default=None, max_length=2000)


class ClientRow(BaseModel):
    client_id: str
    transactions: int
    flagged: int
    last_seen: datetime | None
    max_score: float


class ClientDetail(BaseModel):
    client_id: str
    first_seen: datetime
    last_seen: datetime
    profile: dict[str, Any]
    recent: list[TransactionOut]


class AlertHistoryOut(BaseModel):
    id: int
    transaction_id: str
    client_id: str
    event_type: str
    risk_level: str
    anomaly_score: float
    status: str
    actor: str | None
    comment: str | None
    created_at: datetime
