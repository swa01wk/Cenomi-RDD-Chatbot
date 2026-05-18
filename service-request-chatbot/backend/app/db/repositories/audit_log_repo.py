"""ServiceRequestChatAuditLog repository.

Audit log entries are append-only; there is no update operation.  Reads are
limited to lookup-by-id and listing all entries for a session.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ServiceRequestChatAuditLog

log = structlog.get_logger(__name__)


class AuditLogRepository:
    """Async repository for :class:`~app.db.models.ServiceRequestChatAuditLog`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        session_id: UUID,
        action: str,
        actor_user_id: UUID | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ServiceRequestChatAuditLog:
        """Append a new audit log entry and flush.

        Args:
            session_id:     The owning :class:`ChatSession` id.
            action:         Short action label, e.g. ``"draft.updated"``.
            actor_user_id:  UUID of the user who triggered the action, if known.
            before_state:   Full JSONB state snapshot *before* the action.
            after_state:    Full JSONB state snapshot *after* the action.
            metadata:       Arbitrary supplemental context.
        """
        row = ServiceRequestChatAuditLog(
            session_id=session_id,
            action=action,
            actor_user_id=actor_user_id,
            before_state=before_state,
            after_state=after_state,
            metadata_=metadata if metadata is not None else {},
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "audit_log.created",
            log_id=str(row.id),
            session_id=str(session_id),
            action=action,
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, log_id: UUID) -> ServiceRequestChatAuditLog | None:
        """Return the audit log entry with *log_id*, or ``None``."""
        result = await self._session.execute(
            select(ServiceRequestChatAuditLog).where(
                ServiceRequestChatAuditLog.id == log_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_session(
        self,
        session_id: UUID,
        *,
        limit: int | None = None,
    ) -> list[ServiceRequestChatAuditLog]:
        """Return audit entries for a session in chronological order.

        Args:
            session_id: Filter by this session.
            limit:      Cap the number of returned rows (``None`` = unlimited).
        """
        stmt = (
            select(ServiceRequestChatAuditLog)
            .where(ServiceRequestChatAuditLog.session_id == session_id)
            .order_by(ServiceRequestChatAuditLog.created_at)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars())
