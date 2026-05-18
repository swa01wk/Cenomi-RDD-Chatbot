"""AgentStateSnapshot repository.

Captures full state at BEFORE_NODE / AFTER_NODE / BEFORE_TRACE / AFTER_TRACE
checkpoints.  State payloads are sanitised before storage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStateSnapshot
from app.observability.redaction import sanitise

log = structlog.get_logger(__name__)

VALID_SNAPSHOT_TYPES: frozenset[str] = frozenset(
    {"BEFORE_NODE", "AFTER_NODE", "BEFORE_TRACE", "AFTER_TRACE"}
)


class StateSnapshotRepository:
    """Async repository for :class:`~app.db.models.AgentStateSnapshot`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        trace_id: UUID,
        run_id: UUID,
        snapshot_type: str,
        state: dict[str, Any],
    ) -> AgentStateSnapshot:
        """Insert a new state snapshot.

        ``state`` is sanitised (redacted + CoT stripped) before storage.
        """
        row = AgentStateSnapshot(
            id=uuid4(),
            trace_id=trace_id,
            run_id=run_id,
            snapshot_type=snapshot_type,
            state=sanitise(state),
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_state_snapshot.created",
            snapshot_id=str(row.id),
            trace_id=str(trace_id),
            run_id=str(run_id),
            snapshot_type=snapshot_type,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 200
    ) -> list[AgentStateSnapshot]:
        """Return all snapshots for *trace_id*, oldest first."""
        result = await self._session.execute(
            select(AgentStateSnapshot)
            .where(AgentStateSnapshot.trace_id == trace_id)
            .order_by(AgentStateSnapshot.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_for_run(
        self, run_id: UUID, *, limit: int = 50
    ) -> list[AgentStateSnapshot]:
        """Return all snapshots for *run_id*, oldest first."""
        result = await self._session.execute(
            select(AgentStateSnapshot)
            .where(AgentStateSnapshot.run_id == run_id)
            .order_by(AgentStateSnapshot.created_at)
            .limit(limit)
        )
        return list(result.scalars())
