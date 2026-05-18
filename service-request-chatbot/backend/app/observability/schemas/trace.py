"""Trace DTOs."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TraceCreate:
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TraceRecord:
    trace_id: UUID
    name: str
    metadata: dict[str, Any]
