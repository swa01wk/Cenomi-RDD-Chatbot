"""Run node DTOs (nested spans under a trace)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: UUID
    trace_id: UUID
    parent_run_id: UUID | None
    node_name: str
    started_at: datetime
    ended_at: datetime | None
