"""Service request draft and submission types (placeholders for API contracts)."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ServiceRequestDraftDTO:
    id: UUID
    session_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationIssueDTO:
    code: str
    message: str
    field_key: str | None = None
