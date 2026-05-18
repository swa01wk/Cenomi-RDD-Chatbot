"""Chat-related value types."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID


MessageRole = Literal["user", "assistant", "system"]


@dataclass(frozen=True, slots=True)
class AuthContext:
    subject_id: str
    tenant_id: str | None
    roles: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ChatMessageDTO:
    id: UUID
    session_id: UUID
    role: MessageRole
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatSessionDTO:
    id: UUID
    tenant_id: str | None
    created_at: datetime
    updated_at: datetime
