"""AgentFeedback repository.

Persists explicit user or automated feedback signals attached to a trace.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentFeedback

log = structlog.get_logger(__name__)


class FeedbackRepository:
    """Async repository for :class:`~app.db.models.AgentFeedback`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        trace_id: UUID,
        feedback_type: str,
        run_id: UUID | None = None,
        user_id: UUID | None = None,
        score: int | None = None,
        label: str | None = None,
        comment: str | None = None,
    ) -> AgentFeedback:
        """Insert a new feedback record and flush."""
        row = AgentFeedback(
            id=uuid4(),
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            feedback_type=feedback_type,
            score=score,
            label=label,
            comment=comment,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "agent_feedback.created",
            feedback_id=str(row.id),
            trace_id=str(trace_id),
            feedback_type=feedback_type,
            score=score,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_for_trace(
        self, trace_id: UUID, *, limit: int = 100
    ) -> list[AgentFeedback]:
        """Return all feedback for *trace_id*, oldest first."""
        result = await self._session.execute(
            select(AgentFeedback)
            .where(AgentFeedback.trace_id == trace_id)
            .order_by(AgentFeedback.created_at)
            .limit(limit)
        )
        return list(result.scalars())
