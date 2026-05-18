"""AgentRun repository.

Responsible only for persistence of AgentRun (span) records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.exceptions import RecordNotFoundError
from app.db.models import AgentRun
from app.observability.redaction import sanitise

log = structlog.get_logger(__name__)

VALID_RUN_TYPES: frozenset[str] = frozenset(
    {
        "SUPERVISOR",
        "AGENT",
        "LANGGRAPH_NODE",
        "LLM_CALL",
        "TOOL_CALL",
        "VALIDATION",
        "API_CALL",
        "STATE_UPDATE",
        "RESPONSE_GENERATION",
    }
)


class RunRepository:
    """Async repository for :class:`~app.db.models.AgentRun`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        trace_id: UUID,
        run_name: str,
        run_type: str,
        status: str,
        parent_run_id: UUID | None = None,
        node_name: str | None = None,
        input: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Insert a new AgentRun and flush to obtain the DB-generated id.

        ``input`` is sanitised (redacted + CoT stripped) before storage.
        """
        row = AgentRun(
            id=uuid4(),
            trace_id=trace_id,
            parent_run_id=parent_run_id,
            run_name=run_name,
            run_type=run_type,
            node_name=node_name,
            input=sanitise(input or {}),
            output={},
            status=status,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_run.created",
            run_id=str(row.id),
            trace_id=str(trace_id),
            run_name=run_name,
            run_type=run_type,
        )
        return row

    async def update(self, run_id: UUID, updates: dict[str, Any]) -> AgentRun:
        """Apply a partial update to an existing AgentRun.

        Raises:
            RecordNotFoundError: if no row with *run_id* exists.
        """
        row = await self.get(run_id)
        if row is None:
            raise RecordNotFoundError("AgentRun", run_id)

        for key, value in updates.items():
            setattr(row, key, value)

        await self._session.flush()
        log.debug(
            "agent_run.updated",
            run_id=str(run_id),
            fields=list(updates.keys()),
        )
        return row

    async def complete(
        self,
        run_id: UUID,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        latency_ms: int | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        """Mark a run as completed and record outcome fields.

        ``output`` is sanitised (redacted + CoT stripped) before storage.
        """
        row = await self.get(run_id)
        if row is None:
            raise RecordNotFoundError("AgentRun", run_id)

        row.status = status
        row.completed_at = datetime.now(tz=timezone.utc)
        if output is not None:
            row.output = sanitise(output)
        if latency_ms is not None:
            row.latency_ms = latency_ms
        if error_message is not None:
            row.error_message = error_message

        await self._session.flush()
        log.debug(
            "agent_run.completed",
            run_id=str(run_id),
            status=status,
            latency_ms=latency_ms,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, run_id: UUID) -> AgentRun | None:
        """Return the AgentRun with *run_id*, or ``None``."""
        result = await self._session.execute(
            select(AgentRun).where(AgentRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 200
    ) -> list[AgentRun]:
        """Return all runs for *trace_id*, ordered by start time."""
        result = await self._session.execute(
            select(AgentRun)
            .where(AgentRun.trace_id == trace_id)
            .order_by(AgentRun.started_at)
            .limit(limit)
        )
        return list(result.scalars())
