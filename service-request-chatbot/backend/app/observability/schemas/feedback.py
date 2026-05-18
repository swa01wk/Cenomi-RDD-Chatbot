"""Human feedback on traces/runs."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FeedbackCreate:
    trace_id: UUID
    score: float | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    feedback_id: UUID
    trace_id: UUID
    score: float | None
    comment: str | None
