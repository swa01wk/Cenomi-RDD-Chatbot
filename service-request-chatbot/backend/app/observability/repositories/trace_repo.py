"""AgentTrace repository.

Responsible only for persistence of AgentTrace records.
No orchestration, agent logic, or LLM calls belong here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.exceptions import RecordNotFoundError
from app.db.models import AgentTrace

log = structlog.get_logger(__name__)

_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "active_agent",
        "intent",
        "service_category",
        "sub_category",
        "workflow_stage_before",
        "workflow_stage_after",
        "input_message",
        "output_message",
        "status",
        "error_message",
        "total_latency_ms",
        "total_token_count",
        "estimated_cost",
        "metadata_",
        "completed_at",
    }
)


class TraceRepository:
    """Async repository for :class:`~app.db.models.AgentTrace`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        trace_type: str = "CHAT_TURN",
        status: str,
        active_agent: str | None = None,
        intent: str | None = None,
        service_category: str | None = None,
        sub_category: str | None = None,
        workflow_stage_before: str | None = None,
        input_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTrace:
        """Insert a new AgentTrace and flush to obtain the DB-generated id."""
        row = AgentTrace(
            id=uuid4(),
            session_id=session_id,
            user_id=user_id,
            trace_type=trace_type,
            status=status,
            active_agent=active_agent,
            intent=intent,
            service_category=service_category,
            sub_category=sub_category,
            workflow_stage_before=workflow_stage_before,
            input_message=input_message,
            metadata_=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_trace.created",
            trace_id=str(row.id),
            session_id=str(session_id),
            user_id=str(user_id),
            trace_type=trace_type,
        )
        return row

    async def update(self, trace_id: UUID, updates: dict[str, Any]) -> AgentTrace:
        """Apply a partial update to an existing AgentTrace.

        Only fields listed in ``_UPDATABLE_FIELDS`` may be changed.

        Raises:
            RecordNotFoundError: if no row with *trace_id* exists.
        """
        row = await self.get(trace_id)
        if row is None:
            raise RecordNotFoundError("AgentTrace", trace_id)

        for key, value in updates.items():
            setattr(row, key, value)

        await self._session.flush()
        log.debug(
            "agent_trace.updated",
            trace_id=str(trace_id),
            fields=list(updates.keys()),
        )
        return row

    async def complete(
        self,
        trace_id: UUID,
        *,
        status: str,
        output_message: str | None = None,
        active_agent: str | None = None,
        intent: str | None = None,
        service_category: str | None = None,
        sub_category: str | None = None,
        workflow_stage_before: str | None = None,
        workflow_stage_after: str | None = None,
        total_latency_ms: int | None = None,
        total_token_count: int | None = None,
        estimated_cost: Decimal | None = None,
        error_message: str | None = None,
    ) -> AgentTrace:
        """Mark a trace as completed and record outcome fields."""
        row = await self.get(trace_id)
        if row is None:
            raise RecordNotFoundError("AgentTrace", trace_id)

        row.status = status
        row.completed_at = datetime.now(tz=timezone.utc)
        if output_message is not None:
            row.output_message = output_message
        if active_agent is not None:
            row.active_agent = active_agent
        if intent is not None:
            row.intent = intent
        if service_category is not None:
            row.service_category = service_category
        if sub_category is not None:
            row.sub_category = sub_category
        if workflow_stage_before is not None:
            row.workflow_stage_before = workflow_stage_before
        if workflow_stage_after is not None:
            row.workflow_stage_after = workflow_stage_after
        if total_latency_ms is not None:
            row.total_latency_ms = total_latency_ms
        if total_token_count is not None:
            row.total_token_count = total_token_count
        if estimated_cost is not None:
            row.estimated_cost = estimated_cost
        if error_message is not None:
            row.error_message = error_message

        await self._session.flush()
        log.debug(
            "agent_trace.completed",
            trace_id=str(trace_id),
            status=status,
            total_latency_ms=total_latency_ms,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, trace_id: UUID) -> AgentTrace | None:
        """Return the AgentTrace with *trace_id*, or ``None``."""
        result = await self._session.execute(
            select(AgentTrace).where(AgentTrace.id == trace_id)
        )
        return result.scalar_one_or_none()

    async def list_by_session(
        self, session_id: UUID, *, limit: int = 50
    ) -> list[AgentTrace]:
        """Return traces for *session_id*, most-recent first."""
        result = await self._session.execute(
            select(AgentTrace)
            .where(AgentTrace.session_id == session_id)
            .order_by(AgentTrace.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_by_user(
        self, user_id: UUID, *, limit: int = 50
    ) -> list[AgentTrace]:
        """Return traces for *user_id*, most-recent first."""
        result = await self._session.execute(
            select(AgentTrace)
            .where(AgentTrace.user_id == user_id)
            .order_by(AgentTrace.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_filtered(
        self,
        *,
        status: str | None = None,
        agent: str | None = None,
        intent: str | None = None,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        has_error: bool | None = None,
        min_latency_ms: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentTrace], int]:
        """Return a paginated, filtered list of AgentTrace rows plus total count.

        All filter parameters are optional; omitting them returns all traces.
        Results are ordered most-recent first.

        Returns:
            A (rows, total) tuple where *total* is the unfiltered-page count
            used for building ``has_next`` / ``total`` in the API response.
        """
        conditions = []
        if status is not None:
            conditions.append(AgentTrace.status == status)
        if agent is not None:
            conditions.append(AgentTrace.active_agent == agent)
        if intent is not None:
            conditions.append(AgentTrace.intent == intent)
        if session_id is not None:
            conditions.append(AgentTrace.session_id == session_id)
        if user_id is not None:
            conditions.append(AgentTrace.user_id == user_id)
        if from_date is not None:
            conditions.append(AgentTrace.created_at >= from_date)
        if to_date is not None:
            conditions.append(AgentTrace.created_at <= to_date)
        if has_error is True:
            conditions.append(AgentTrace.error_message.isnot(None))
        elif has_error is False:
            conditions.append(AgentTrace.error_message.is_(None))
        if min_latency_ms is not None:
            conditions.append(AgentTrace.total_latency_ms >= min_latency_ms)

        where_clause = and_(*conditions) if conditions else None

        # --- total count ---
        count_stmt = select(func.count(AgentTrace.id))
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
        count_result = await self._session.execute(count_stmt)
        total: int = count_result.scalar_one()

        # --- paged rows ---
        offset = (page - 1) * page_size
        stmt = select(AgentTrace).order_by(AgentTrace.created_at.desc()).offset(offset).limit(page_size)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        rows_result = await self._session.execute(stmt)
        rows = list(rows_result.scalars())

        log.debug(
            "agent_trace.list_filtered",
            total=total,
            page=page,
            page_size=page_size,
            returned=len(rows),
        )
        return rows, total
