"""ChatSession repository.

Responsible only for persistence of ChatSession records.  No orchestration,
no agent logic, no LLM calls belong here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ChatSession

log = structlog.get_logger(__name__)

_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {"active_agent", "intent", "workflow_stage", "status"}
)


class ChatSessionRepository:
    """Async repository for :class:`~app.db.models.ChatSession`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: UUID,
        active_agent: str | None = None,
        intent: str | None = None,
        workflow_stage: str | None = None,
        status: str = "IN_PROGRESS",
    ) -> ChatSession:
        """Insert a new ChatSession and flush to obtain the DB-generated id.

        The caller's outer transaction (or ``get_db_session``) is responsible
        for the final commit.
        """
        row = ChatSession(
            user_id=user_id,
            active_agent=active_agent,
            intent=intent,
            workflow_stage=workflow_stage,
            status=status,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug("chat_session.created", session_id=str(row.id), user_id=str(user_id))
        return row

    async def update(self, session_id: UUID, updates: dict[str, Any]) -> ChatSession:
        """Apply a partial update to an existing ChatSession.

        Only fields listed in ``_UPDATABLE_FIELDS`` may be changed.

        Raises:
            RecordNotFoundError: if no row with *session_id* exists.
            InvalidUpdateFieldError: if *updates* contains a non-updatable key.
        """
        row = await self.get_by_id(session_id)
        if row is None:
            raise RecordNotFoundError("ChatSession", session_id)

        for key, value in updates.items():
            if key not in _UPDATABLE_FIELDS:
                raise InvalidUpdateFieldError("ChatSession", key)
            setattr(row, key, value)

        await self._session.flush()
        log.debug(
            "chat_session.updated",
            session_id=str(session_id),
            fields=list(updates.keys()),
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, session_id: UUID) -> ChatSession | None:
        """Return the ChatSession with *session_id*, or ``None``."""
        result = await self._session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()
