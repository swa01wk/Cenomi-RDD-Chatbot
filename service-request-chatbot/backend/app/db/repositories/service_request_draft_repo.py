"""ServiceRequestDraft repository.

Stores the collected fields, documents, and submission status for a
service-request draft.  Multiple drafts per session are supported (one per
workflow run); use ``get_by_session`` to retrieve the most recent one.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.exceptions import InvalidUpdateFieldError, RecordNotFoundError
from app.db.models import ServiceRequestDraft

log = structlog.get_logger(__name__)

_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "service_category",
        "sub_category",
        "workflow_stage",
        "collected_data",
        "missing_fields",
        "documents",
        "sr_id",
        "service_request_status",
        "ready_to_submit",
    }
)


class ServiceRequestDraftRepository:
    """Async repository for :class:`~app.db.models.ServiceRequestDraft`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        session_id: UUID,
        service_category: str,
        sub_category: str,
        workflow_stage: str,
        collected_data: dict[str, Any] | None = None,
        missing_fields: list[Any] | None = None,
        documents: list[Any] | None = None,
        sr_id: str | None = None,
        service_request_status: str | None = None,
        ready_to_submit: bool = False,
    ) -> ServiceRequestDraft:
        """Create a new draft record and flush to obtain the generated id."""
        row = ServiceRequestDraft(
            session_id=session_id,
            service_category=service_category,
            sub_category=sub_category,
            workflow_stage=workflow_stage,
            collected_data=collected_data if collected_data is not None else {},
            missing_fields=missing_fields if missing_fields is not None else [],
            documents=documents if documents is not None else [],
            sr_id=sr_id,
            service_request_status=service_request_status,
            ready_to_submit=ready_to_submit,
        )
        self._session.add(row)
        await self._session.flush()
        log.debug(
            "sr_draft.created",
            draft_id=str(row.id),
            session_id=str(session_id),
            service_category=service_category,
        )
        return row

    async def update(self, draft_id: UUID, updates: dict[str, Any]) -> ServiceRequestDraft:
        """Apply a partial update to a draft.

        Raises:
            RecordNotFoundError: if no draft with *draft_id* exists.
            InvalidUpdateFieldError: if *updates* contains a non-updatable key.
        """
        row = await self.get_by_id(draft_id)
        if row is None:
            raise RecordNotFoundError("ServiceRequestDraft", draft_id)

        for key, value in updates.items():
            if key not in _UPDATABLE_FIELDS:
                raise InvalidUpdateFieldError("ServiceRequestDraft", key)
            setattr(row, key, value)

        await self._session.flush()
        log.debug(
            "sr_draft.updated",
            draft_id=str(draft_id),
            fields=list(updates.keys()),
        )
        return row

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, draft_id: UUID) -> ServiceRequestDraft | None:
        """Return the draft with *draft_id*, or ``None``."""
        result = await self._session.execute(
            select(ServiceRequestDraft).where(ServiceRequestDraft.id == draft_id)
        )
        return result.scalar_one_or_none()

    async def get_by_session(self, session_id: UUID) -> ServiceRequestDraft | None:
        """Return the most recent draft for a session, or ``None``.

        Useful for the common case where a session has exactly one active draft.
        """
        result = await self._session.execute(
            select(ServiceRequestDraft)
            .where(ServiceRequestDraft.session_id == session_id)
            .order_by(ServiceRequestDraft.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: UUID) -> list[ServiceRequestDraft]:
        """Return all drafts for a session ordered by creation time (oldest first)."""
        result = await self._session.execute(
            select(ServiceRequestDraft)
            .where(ServiceRequestDraft.session_id == session_id)
            .order_by(ServiceRequestDraft.created_at)
        )
        return list(result.scalars())
