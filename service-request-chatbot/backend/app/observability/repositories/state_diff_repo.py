"""AgentStateDiff repository.

Persists deltas between successive agent states within a trace.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStateDiff
from app.observability.redaction import sanitise

log = structlog.get_logger(__name__)


class StateDiffRepository:
    """Async repository for :class:`~app.db.models.AgentStateDiff`."""

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
        diff: dict[str, Any],
    ) -> AgentStateDiff:
        """Insert a new state diff.

        ``diff`` is sanitised (redacted + CoT stripped) before storage.
        """
        row = AgentStateDiff(
            id=uuid4(),
            trace_id=trace_id,
            run_id=run_id,
            diff=sanitise(diff),
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_state_diff.created",
            diff_id=str(row.id),
            trace_id=str(trace_id),
            run_id=str(run_id),
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 200
    ) -> list[AgentStateDiff]:
        """Return all diffs for *trace_id*, oldest first."""
        result = await self._session.execute(
            select(AgentStateDiff)
            .where(AgentStateDiff.trace_id == trace_id)
            .order_by(AgentStateDiff.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_for_run(
        self, run_id: UUID, *, limit: int = 50
    ) -> list[AgentStateDiff]:
        """Return all diffs for *run_id*, oldest first."""
        result = await self._session.execute(
            select(AgentStateDiff)
            .where(AgentStateDiff.run_id == run_id)
            .order_by(AgentStateDiff.created_at)
            .limit(limit)
        )
        return list(result.scalars())
