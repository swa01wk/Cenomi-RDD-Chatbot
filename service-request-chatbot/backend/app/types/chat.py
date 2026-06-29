"""Chat-related value types."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID


MessageRole = Literal["user", "assistant", "system"]


@dataclass(frozen=True, slots=True)
class AuthContext:
    subject_id: str
    tenant_id: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    # Mall-level scoping for RLS — populated from JWT claims
    unique_property_ids: tuple[int, ...] = field(default_factory=tuple)
    mall_names: tuple[str, ...] = field(default_factory=tuple)
    is_global_admin: bool = False


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
