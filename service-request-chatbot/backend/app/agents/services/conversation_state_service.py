"""Hydrate / persist conversation aggregates.

Responsible for mapping between the DB ``ServiceRequestDraft`` table and the
flat state dict that LangGraph nodes read/write.  No LLM calls, no routing
logic belong here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.service_request_draft_repo import ServiceRequestDraftRepository

log = structlog.get_logger(__name__)


class ConversationStateService:
    """Load and persist draft state for a service-request conversation session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._draft_repo = ServiceRequestDraftRepository(session)

    async def load(self, session_id: UUID) -> dict[str, Any]:
        """Return the latest draft fields for *session_id*, or ``{}`` if none exists.

        Workflow metadata embedded in ``collected_data`` by ``save_checkpoint``
        (``_confirmation_status``, ``_selected_lease``) is extracted into
        top-level state keys so graph nodes see a clean interface.
        """
        try:
            draft = await self._draft_repo.get_by_session(session_id)
            if draft is None:
                return {}

            raw_collected: dict[str, Any] = dict(draft.collected_data or {})

            # Extract embedded workflow metadata back into top-level state keys.
            confirmation_status = raw_collected.pop("_confirmation_status", None)
            selected_lease = raw_collected.pop("_selected_lease", None)

            result: dict[str, Any] = {
                "service_category": draft.service_category,
                "sub_category": draft.sub_category,
                "workflow_stage": draft.workflow_stage,
                "collected_data": raw_collected,
                "missing_fields": draft.missing_fields or [],
                "documents": draft.documents or [],
            }
            if confirmation_status is not None:
                result["confirmation_status"] = confirmation_status
            if selected_lease is not None:
                result["selected_lease"] = selected_lease
            return result
        except Exception:
            log.exception("conversation_state_service.load.failed", session_id=str(session_id))
            return {}

    async def save_checkpoint(self, session_id: UUID, state: dict[str, Any]) -> None:
        """Upsert draft state after a completed graph turn.

        Creates a new draft row when the graph has identified a service
        category; skips persistence when the intent is not yet resolved.

        ``confirmation_status`` and ``selected_lease`` are not DB columns, so
        they are piggy-backed into ``collected_data`` under reserved ``_``-prefixed
        keys (``_confirmation_status``, ``_selected_lease``).  ``load`` strips them
        back out into top-level state keys so nodes never see the raw storage.
        """
        try:
            service_category = state.get("service_category")
            sub_category = state.get("sub_category") or ""
            workflow_stage = state.get("workflow_stage") or "CREATE_SR"
            ready_to_submit = state.get("status") in ("READY_TO_SUBMIT", "SUBMITTED")

            # Build the collected_data to persist, embedding workflow metadata
            # that has no dedicated DB column.
            raw_collected: dict[str, Any] = dict(state.get("collected_data") or {})
            confirmation_status = state.get("confirmation_status")
            if confirmation_status is not None:
                raw_collected["_confirmation_status"] = confirmation_status
            else:
                raw_collected.pop("_confirmation_status", None)

            selected_lease = state.get("selected_lease")
            if selected_lease is not None:
                raw_collected["_selected_lease"] = selected_lease
            else:
                raw_collected.pop("_selected_lease", None)

            draft = await self._draft_repo.get_by_session(session_id)

            if draft is None:
                if not service_category:
                    log.debug(
                        "conversation_state_service.save_checkpoint.skipped_no_category",
                        session_id=str(session_id),
                    )
                    return
                await self._draft_repo.create(
                    session_id=session_id,
                    service_category=service_category,
                    sub_category=sub_category,
                    workflow_stage=workflow_stage,
                    collected_data=raw_collected,
                    missing_fields=state.get("missing_fields") or [],
                    documents=state.get("documents") or [],
                    ready_to_submit=ready_to_submit,
                    sr_id=_extract_sr_id(state),
                )
            else:
                updates: dict[str, Any] = {
                    "workflow_stage": workflow_stage,
                    # Use raw_collected unconditionally — an empty dict after a
                    # restart must CLEAR the draft, not fall back to stale data.
                    # The old `if raw_collected else draft.collected_data` guard
                    # treated {} as falsy and silently re-persisted the old
                    # collected_data, causing context leakage into the next request.
                    "collected_data": raw_collected,
                    "missing_fields": state.get("missing_fields") or [],
                    "documents": state.get("documents") or draft.documents,
                    "ready_to_submit": ready_to_submit,
                }
                if service_category:
                    updates["service_category"] = service_category
                if sub_category:
                    updates["sub_category"] = sub_category
                sr_id = _extract_sr_id(state)
                if sr_id:
                    updates["sr_id"] = sr_id
                await self._draft_repo.update(draft.id, updates)

            log.debug(
                "conversation_state_service.save_checkpoint.ok",
                session_id=str(session_id),
                workflow_stage=workflow_stage,
            )
        except Exception:
            log.exception(
                "conversation_state_service.save_checkpoint.failed",
                session_id=str(session_id),
            )


def _extract_sr_id(state: dict[str, Any]) -> str | None:
    backend_refs = state.get("backend_refs") or {}
    return backend_refs.get("sr_id") or backend_refs.get("service_request_id")
