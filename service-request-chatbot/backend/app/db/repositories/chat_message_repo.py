"""ChatMessage repository.

Chat messages are largely immutable once written; the only post-creation
mutation allowed is updating the ``metadata`` bag (e.g., to attach tool
output, token counts, or UI annotations after the fact).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ChatMessage

log = structlog.get_logger(__name__)

_UPDATABLE_FIELDS: frozenset[str] = frozenset({"metadata_"})


class ChatMessageRepository:
    """Async repository for :class:`~app.db.models.ChatMessage`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        session_id: UUID,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> ChatMessage:
        """Append a new message to a session and flush.

        Args:
            session_id:  The owning :class:`ChatSession` id.
            role:        ``"user"``, ``"assistant"``, or ``"system"``.
            content:     Message body text.
            metadata:    Optional JSONB bag for auxiliary data (tokens, etc.).
            created_at:  Explicit timestamp for ordering.  When provided it is
                         stored as-is (overriding the ``server_default``).
                         Pass ``datetime.now(timezone.utc)`` from the caller
                         so user and assistant messages within the same DB
                         transaction get distinct, correctly-ordered timestamps
                         (PostgreSQL ``NOW()`` returns the *transaction start*
                         time, which would make both messages identical).
        """
        kwargs: dict[str, Any] = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata_": metadata if metadata is not None else {},
        }
        if created_at is not None:
            kwargs["created_at"] = created_at
        row = ChatMessage(**kwargs)
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "chat_message.created",
            message_id=str(row.id),
            session_id=str(session_id),
            role=role,
        )
        return row

    async def update(self, message_id: UUID, updates: dict[str, Any]) -> ChatMessage:
        """Update mutable fields on an existing message.

        Only ``metadata_`` is updatable.

        Raises:
            RecordNotFoundError: if no row with *message_id* exists.
            InvalidUpdateFieldError: if *updates* contains a non-updatable key.
        """
        row = await self.get_by_id(message_id)
        if row is None:
            raise RecordNotFoundError("ChatMessage", message_id)

        for key, value in updates.items():
            if key not in _UPDATABLE_FIELDS:
                raise InvalidUpdateFieldError("ChatMessage", key)
            setattr(row, key, value)

        await self._session.flush()
        log.debug("chat_message.updated", message_id=str(message_id))
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, message_id: UUID) -> ChatMessage | None:
        """Return the ChatMessage with *message_id*, or ``None``."""
        result = await self._session.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: UUID) -> list[ChatMessage]:
        """Return all messages for a session ordered by creation time."""
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars())

    async def list_recent_by_session(
        self, session_id: UUID, limit: int = 10
    ) -> list[ChatMessage]:
        """Return the most recent *limit* messages, returned oldest-first for context windows."""
        from sqlalchemy import desc

        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(limit)
        )
        rows = list(result.scalars())
        rows.reverse()
        return rows
