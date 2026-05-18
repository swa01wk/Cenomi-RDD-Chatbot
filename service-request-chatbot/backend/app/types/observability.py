"""Observability domain types (runs, traces, snapshots)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TraceSummaryDTO:
    trace_id: UUID
    name: str
    started_at: datetime
    ended_at: datetime | None
    status: str


@dataclass(frozen=True, slots=True)
class RunNodeDTO:
    run_id: UUID
    parent_run_id: UUID | None
    node_name: str
    started_at: datetime
    ended_at: datetime | None
    status: str


@dataclass(frozen=True, slots=True)
class StateSnapshotDTO:
    snapshot_id: UUID
    run_id: UUID
    captured_at: datetime
    diff_from_previous: dict[str, Any] | None
