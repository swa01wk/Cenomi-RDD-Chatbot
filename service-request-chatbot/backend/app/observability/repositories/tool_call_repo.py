"""AgentToolCall repository.

Records external tool invocations.  Request and response payloads are
sanitised before storage to prevent credential leakage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentToolCall
from app.observability.redaction import sanitise

log = structlog.get_logger(__name__)

VALID_TOOL_TYPES: frozenset[str] = frozenset(
    {
        "LEASE_LOOKUP",
        "DOCUMENT_UPLOAD",
        "SERVICE_REQUEST_CREATE",
        "SERVICE_REQUEST_PATCH",
        "PERMISSION_CHECK",
    }
)


class ToolCallRepository:
    """Async repository for :class:`~app.db.models.AgentToolCall`."""

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
        tool_name: str,
        tool_type: str,
        request_payload: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
        status_code: int | None = None,
        success: bool | None = None,
        latency_ms: int | None = None,
        error_message: str | None = None,
    ) -> AgentToolCall:
        """Insert a new tool call record.

        Both ``request_payload`` and ``response_payload`` are sanitised
        (redacted + CoT stripped) before storage.
        """
        row = AgentToolCall(
            id=uuid4(),
            trace_id=trace_id,
            run_id=run_id,
            tool_name=tool_name,
            tool_type=tool_type,
            request_payload=sanitise(request_payload or {}),
            response_payload=sanitise(response_payload or {}),
            status_code=status_code,
            success=success,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_tool_call.created",
            tool_call_id=str(row.id),
            trace_id=str(trace_id),
            run_id=str(run_id),
            tool_name=tool_name,
            tool_type=tool_type,
            success=success,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 200
    ) -> list[AgentToolCall]:
        """Return all tool calls for *trace_id*, oldest first."""
        result = await self._session.execute(
            select(AgentToolCall)
            .where(AgentToolCall.trace_id == trace_id)
            .order_by(AgentToolCall.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def list_for_run(
        self, run_id: UUID, *, limit: int = 50
    ) -> list[AgentToolCall]:
        """Return all tool calls for *run_id*, oldest first."""
        result = await self._session.execute(
            select(AgentToolCall)
            .where(AgentToolCall.run_id == run_id)
            .order_by(AgentToolCall.created_at)
            .limit(limit)
        )
        return list(result.scalars())
