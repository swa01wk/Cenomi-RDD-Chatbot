"""Chat orchestration service.

This service is the single entry point that the HTTP layer calls for every
chat turn.  It owns the turn lifecycle:

  1. Load or create ChatSession
  2. Start observability trace
  3. Audit: turn started
  4. Persist user message
  5. Build initial LangGraph state (inject services, carry forward session fields)
  6. Invoke compiled graph
  7. Finish / fail trace
  8. Persist assistant message
  9. Update ChatSession from graph result
 10. Audit: turn completed
 11. Return ChatTurnResult

Principle: this service delegates graph routing and LLM work to LangGraph.
It never contains business workflow logic — validation, field extraction,
submission are concerns of graph nodes and domain services.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph.service_request_graph import get_compiled_graph
from app.agents.services.conversation_state_service import ConversationStateService
from app.core.injection_guard import scan_message
from app.db.models import ChatSession
from app.db.repositories.audit_log_repo import AuditLogRepository
from app.db.repositories.chat_message_repo import ChatMessageRepository
from app.db.repositories.chat_session_repo import ChatSessionRepository
from app.observability.trace_manager import TraceManager

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatTurnState:
    intent: str | None
    workflow_stage: str | None
    missing_fields: list[str]
    ready_to_submit: bool


@dataclass(frozen=True, slots=True)
class ChatTurnResult:
    session_id: UUID
    active_agent: str | None
    message: str
    ui: dict[str, Any]
    state: ChatTurnState
    trace_id: UUID | None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ChatOrchestrationService:
    """Orchestrate a single chat turn end-to-end."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._session_repo = ChatSessionRepository(db)
        self._message_repo = ChatMessageRepository(db)
        self._audit_repo = AuditLogRepository(db)
        self._trace_manager = TraceManager(db)
        self._state_service = ConversationStateService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_turn(
        self,
        *,
        session_id: UUID | None,
        user_id: UUID,
        message: str,
        attachments: list[dict[str, Any]],
        action: str | None = None,
        selected_lease_id: str | None = None,
        corrected_fields: dict[str, Any] | None = None,
    ) -> ChatTurnResult:
        """Execute one complete chat turn and return structured result."""

        # 1. Load or create session ----------------------------------------
        chat_session = await self._load_or_create_session(session_id, user_id)
        session_uuid = chat_session.id

        log.info(
            "chat.turn_started",
            session_id=str(session_uuid),
            user_id=str(user_id),
            is_new_session=(session_id is None or chat_session.id != session_id),
        )

        # 2. Start trace -------------------------------------------------------
        trace_id = await self._trace_manager.start_trace(
            session_id=session_uuid,
            user_id=user_id,
            input_message=message,
            metadata={"attachments_count": len(attachments)},
        )

        # 3. Audit: turn started -----------------------------------------------
        await self._audit_repo.create(
            session_id=session_uuid,
            action="turn.started",
            actor_user_id=user_id,
            metadata={"trace_id": str(trace_id) if trace_id else None},
        )

        # 3b. Load recent conversation history (before persisting current msg) ----
        recent_msgs = await self._message_repo.list_recent_by_session(
            session_uuid, limit=10
        )
        conversation_history = [
            {"role": m.role, "content": m.content} for m in recent_msgs
        ]

        # 3c. Prompt-injection scan -------------------------------------------
        # Run before the user message is persisted so that high-risk content
        # never reaches the graph or the message store.
        scan_result = scan_message(message)

        if scan_result.matched_patterns:
            log.warning(
                "security.suspicious_input",
                session_id=str(session_uuid),
                user_id=str(user_id),
                risk_score=scan_result.risk_score,
                matched_patterns=scan_result.matched_patterns,
                is_high_risk=scan_result.is_high_risk,
            )

        if scan_result.is_high_risk:
            # Audit the attempt — store only scan metadata, not the raw message.
            await self._audit_repo.create(
                session_id=session_uuid,
                action="security.injection_attempt",
                actor_user_id=user_id,
                metadata={
                    "risk_score": scan_result.risk_score,
                    "matched_patterns": scan_result.matched_patterns,
                    "reason": scan_result.reason,
                    "trace_id": str(trace_id) if trace_id else None,
                },
            )
            if trace_id:
                await self._trace_manager.fail_trace(
                    trace_id=trace_id,
                    error_message="Blocked: high-risk prompt injection detected.",
                    workflow_stage_before=chat_session.workflow_stage,
                )
            refusal = (
                "I'm sorry, but I can't process that request. "
                "If you need help with a Handover Service Request, "
                "please describe what you'd like to do."
            )
            return ChatTurnResult(
                session_id=session_uuid,
                active_agent=None,
                message=refusal,
                ui={"type": "message"},
                state=ChatTurnState(
                    intent=None,
                    workflow_stage=None,
                    missing_fields=[],
                    ready_to_submit=False,
                ),
                trace_id=trace_id,
            )

        # 4. Persist user message -----------------------------------------------
        # Capture an explicit Python-side timestamp so that the user message and
        # the assistant reply (persisted after graph invocation) get distinct
        # created_at values.  PostgreSQL NOW() returns the *transaction start*
        # time — both INSERTs in a single transaction would otherwise share the
        # same microsecond, making list_recent_by_session ordering undefined.
        user_msg_time = datetime.now(timezone.utc)
        await self._message_repo.create(
            session_id=session_uuid,
            role="user",
            content=message,
            metadata={
                "attachments": attachments,
                "trace_id": str(trace_id) if trace_id else None,
            },
            created_at=user_msg_time,
        )

        # 5. Build initial graph state -----------------------------------------
        initial_state: dict[str, Any] = {
            "session_id": str(session_uuid),
            "user_id": str(user_id),
            "user_message": message,
            "attachments": attachments,
            "trace_id": str(trace_id) if trace_id else "",
            "conversation_history": conversation_history,
            # Non-serialisable runtime services (dropped by serializers before trace persist)
            "trace_manager": self._trace_manager,
            "conversation_state_service": self._state_service,
            # Carry forward routing state so the graph skips re-classification
            "active_agent": chat_session.active_agent,
            "intent": chat_session.intent,
            "workflow_stage": chat_session.workflow_stage,
        }

        # Inject UI-layer overrides so graph nodes can act on explicit button
        # actions and inline card edits without relying solely on text parsing.
        if action is not None:
            initial_state["action_override"] = action
        if corrected_fields:
            initial_state["corrected_fields"] = corrected_fields
        if selected_lease_id:
            initial_state["selected_lease"] = {"id": selected_lease_id}

        # 6. Invoke graph -------------------------------------------------------
        result_state: dict[str, Any]
        try:
            graph = get_compiled_graph()
            result_state = await graph.ainvoke(initial_state)
        except Exception as exc:
            log.exception(
                "chat.graph_invocation_failed",
                session_id=str(session_uuid),
                trace_id=str(trace_id) if trace_id else None,
            )
            if trace_id:
                await self._trace_manager.fail_trace(
                    trace_id=trace_id,
                    error_message=str(exc),
                    workflow_stage_before=chat_session.workflow_stage,
                )
            await self._audit_repo.create(
                session_id=session_uuid,
                action="turn.failed",
                actor_user_id=user_id,
                metadata={
                    "error": str(exc),
                    "trace_id": str(trace_id) if trace_id else None,
                },
            )
            raise

        # 7. Extract response fields from graph result -------------------------
        response_message: str = (
            result_state.get("response_message") or "I'm processing your request."
        )
        response_ui: dict[str, Any] = result_state.get("response_ui") or {"type": "message"}
        active_agent: str | None = result_state.get("active_agent")
        graph_status: str = result_state.get("status") or "IN_PROGRESS"

        # 8. Finish trace -------------------------------------------------------
        if trace_id:
            await self._trace_manager.finish_trace(
                trace_id=trace_id,
                output_message=response_message,
                final_state=result_state,
                active_agent=result_state.get("active_agent"),
                intent=result_state.get("intent"),
                service_category=result_state.get("service_category"),
                sub_category=result_state.get("sub_category"),
                workflow_stage_before=chat_session.workflow_stage,
                workflow_stage_after=result_state.get("workflow_stage"),
            )

        # 9. Persist assistant reply -------------------------------------------
        assistant_msg_time = datetime.now(timezone.utc)
        await self._message_repo.create(
            session_id=session_uuid,
            role="assistant",
            content=response_message,
            metadata={
                "active_agent": active_agent,
                "status": graph_status,
                "trace_id": str(trace_id) if trace_id else None,
            },
            created_at=assistant_msg_time,
        )

        # 10. Update session routing state -------------------------------------
        await self._sync_session(chat_session, result_state, graph_status)

        # 11. Audit: turn completed --------------------------------------------
        await self._audit_repo.create(
            session_id=session_uuid,
            action="turn.completed",
            actor_user_id=user_id,
            after_state={
                "active_agent": active_agent,
                "workflow_stage": result_state.get("workflow_stage"),
                "status": graph_status,
            },
            metadata={"trace_id": str(trace_id) if trace_id else None},
        )

        log.info(
            "chat.turn_completed",
            session_id=str(session_uuid),
            active_agent=active_agent,
            graph_status=graph_status,
            trace_id=str(trace_id) if trace_id else None,
        )

        # 12. Build and return result ------------------------------------------
        missing_fields: list[str] = result_state.get("missing_fields") or []
        ready_to_submit = graph_status in ("READY_TO_SUBMIT", "SUBMITTED")

        return ChatTurnResult(
            session_id=session_uuid,
            active_agent=active_agent,
            message=response_message,
            ui=response_ui,
            state=ChatTurnState(
                intent=result_state.get("intent"),
                workflow_stage=result_state.get("workflow_stage"),
                missing_fields=missing_fields,
                ready_to_submit=ready_to_submit,
            ),
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_or_create_session(
        self, session_id: UUID | None, user_id: UUID
    ) -> ChatSession:
        """Return an existing ChatSession or create a fresh one.

        If *session_id* is provided and found in the DB, that session is
        returned.  If it is not found (e.g. client sent a stale UUID), a new
        session is created so the turn succeeds without error.
        """
        if session_id is not None:
            existing = await self._session_repo.get_by_id(session_id)
            if existing is not None:
                log.debug("chat.session_loaded", session_id=str(session_id))
                return existing
            log.warning(
                "chat.session_not_found_creating_new",
                requested_session_id=str(session_id),
                user_id=str(user_id),
            )

        new_session = await self._session_repo.create(user_id=user_id)
        log.info("chat.session_created", session_id=str(new_session.id))
        return new_session

    async def _sync_session(
        self,
        chat_session: ChatSession,
        result_state: dict[str, Any],
        graph_status: str,
    ) -> None:
        """Persist routing fields that changed during this turn."""
        updates: dict[str, Any] = {}

        new_agent = result_state.get("active_agent")
        # Include None so that a restart (which clears active_agent) is
        # persisted immediately.  The old `if new_agent` guard skipped the
        # update when active_agent became None, leaving the DB stale and
        # causing the next turn to start with the wrong agent context.
        if new_agent != chat_session.active_agent:
            updates["active_agent"] = new_agent

        new_intent = result_state.get("intent")
        if new_intent != chat_session.intent:
            updates["intent"] = new_intent

        new_stage = result_state.get("workflow_stage")
        if new_stage and new_stage != chat_session.workflow_stage:
            updates["workflow_stage"] = new_stage

        if graph_status in ("COMPLETED", "SUBMITTED"):
            updates["status"] = "COMPLETED"

        if updates:
            await self._session_repo.update(chat_session.id, updates)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def user_id_to_uuid(user_id: str) -> UUID:
    """Map a string user-id to a UUID.

    Tries to parse directly as a UUID first (e.g. ``"550e8400-e29b-41d4-…"``).
    Falls back to a deterministic ``uuid5`` derivation so that ``"user_456"``
    always maps to the same stable UUID.  This allows the POC to accept
    arbitrary user-id strings while still satisfying the DB's UUID column.
    """
    try:
        return UUID(user_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_OID, user_id)


def parse_session_id(session_id: str | None) -> UUID | None:
    """Parse an optional session-id string into a UUID.

    Returns ``None`` for ``None`` input or any non-UUID string so the caller
    creates a fresh session rather than raising a validation error.
    """
    if session_id is None:
        return None
    try:
        return UUID(session_id)
    except ValueError:
        log.warning("chat.invalid_session_id_ignored", raw=session_id)
        return None
