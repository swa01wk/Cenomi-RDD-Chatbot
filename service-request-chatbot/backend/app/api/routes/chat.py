"""Chat HTTP API.

Two routers are exported:

``router``
    Mounted at ``/api/v1`` — houses the original ``POST /chat/turn`` stub
    (kept for backward compatibility).

``service_request_router``
    Mounted at ``/api`` — houses the main ``POST /chat/service-request``
    endpoint described in the product spec.

Principle: no business workflow logic lives here.  The route handler
validates the request, delegates to ``ChatOrchestrationService``, and maps
the result back to the HTTP response contract.  Auth context is stubbed for
the POC; ``user_id`` is accepted in the request body and will move to a JWT
claim in production.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import get_auth_context
from app.db.session import DbSession
from app.services.chat_orchestration_service import (
    ChatOrchestrationService,
    parse_session_id,
    user_id_to_uuid,
)
from app.types.chat import AuthContext
from fastapi import Depends

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Original v1 router — backward-compatible stub
router = APIRouter()

# New service-request chat router mounted at /api (no version prefix)
service_request_router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models — POST /api/chat/service-request
# ---------------------------------------------------------------------------


class ServiceRequestChatRequest(BaseModel):
    """Incoming chat turn for the service-request workflow."""

    session_id: str | None = Field(
        default=None,
        description="Existing session UUID. Omit (or send null) to start a new conversation.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    user_id: str = Field(
        min_length=1,
        description="Caller's user identifier (used when no JWT is present — POC fallback).",
        examples=["user_456", "550e8400-e29b-41d4-a716-446655440001"],
    )
    message: str = Field(
        default="",
        description=(
            "The user's natural-language message. "
            "May be empty only when sr_id is provided (FM/DD opening an existing SR). "
            "Must have at least 1 character when sr_id is absent."
        ),
        examples=["I want to raise a handover request for Under Armour in Jawharat Jeddah"],
    )
    attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional list of file attachment metadata.",
    )
    action: str | None = Field(
        default=None,
        description=(
            "Explicit UI action that bypasses text-based intent parsing. "
            "'confirm' triggers immediate SR submission; 'cancel' resets the confirmation."
        ),
        examples=["confirm", "cancel"],
    )
    selected_lease_id: str | None = Field(
        default=None,
        description="Lease ID chosen from a lease_selection card.",
        examples=["t0105712"],
    )
    corrected_fields: dict[str, Any] | None = Field(
        default=None,
        description="Inline field edits submitted from the confirmation card.",
    )
    sr_id: str | None = Field(
        default=None,
        description=(
            "Platform SR ID — passed by the frontend when FM Manager or DD Engineer opens "
            "an existing SR from a notification or SR list. Triggers sr_status_sync."
        ),
        examples=["SR-2026-00741"],
    )


class ChatStatePayload(BaseModel):
    """Workflow state summary returned alongside the assistant reply."""

    intent: str | None = None
    workflow_stage: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    ready_to_submit: bool = False


class ServiceRequestChatResponse(BaseModel):
    """Response envelope for ``POST /api/chat/service-request``."""

    session_id: str = Field(description="Session UUID (create once, reuse for the whole flow).")
    active_agent: str | None = Field(
        default=None,
        description="The LangGraph agent that handled this turn.",
    )
    message: str = Field(description="Assistant reply to display in the chat UI.")
    ui: dict[str, Any] = Field(
        default_factory=lambda: {"type": "message"},
        description="UI rendering hint emitted by the graph (message, form, selection, etc.).",
    )
    draft_preview: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Current draft SR snapshot (type='sr_preview_card').  "
            "Present on every turn where collected_data is non-empty and the SR "
            "has not yet been submitted.  Allows the frontend to keep its preview "
            "card in sync even when `ui` is a plain message or confirmation type."
        ),
    )
    faq_sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "RAG citations returned by the FAQ node.  "
            "Each item has ``source_type`` and ``title`` keys.  "
            "Empty list when RAG was unavailable or the turn was not a FAQ query."
        ),
    )
    state: ChatStatePayload
    trace_id: str | None = Field(
        default=None,
        description="Observability trace ID for this turn.",
    )


# ---------------------------------------------------------------------------
# POST /chat/service-request
# ---------------------------------------------------------------------------


@service_request_router.post(
    "/chat/service-request",
    response_model=ServiceRequestChatResponse,
    summary="Service-request chat turn",
    description=(
        "Submit one user message to the service-request chatbot.  "
        "The endpoint orchestrates LangGraph, persists messages and session state, "
        "and returns the assistant reply with workflow metadata."
    ),
    responses={
        status.HTTP_200_OK: {"description": "Turn processed successfully."},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Request validation failed."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Graph or persistence error."},
    },
)
async def post_service_request_chat(
    body: ServiceRequestChatRequest,
    db: DbSession,
    auth: AuthContext = Depends(get_auth_context),
) -> ServiceRequestChatResponse:
    """Process one chat turn for the service-request workflow."""
    # Validate: empty message is only allowed when sr_id is present (FM/DD opening existing SR)
    if not body.message and not body.sr_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'message' or 'sr_id' must be provided.",
        )

    # Resolve user_id: JWT subject_id takes precedence over request body user_id
    effective_user_id: str = (
        auth.subject_id
        if auth.subject_id not in ("anonymous", "unauthenticated")
        else body.user_id
    )

    bound_log = log.bind(
        user_id=effective_user_id,
        raw_session_id=body.session_id,
        role=next(iter(auth.roles), "none"),
    )
    bound_log.info("api.chat.service_request.received")

    user_uuid: UUID = user_id_to_uuid(effective_user_id)
    session_uuid: UUID | None = parse_session_id(body.session_id)

    service = ChatOrchestrationService(db)

    try:
        result = await service.process_turn(
            session_id=session_uuid,
            user_id=user_uuid,
            message=body.message,
            attachments=body.attachments,
            action=body.action,
            selected_lease_id=body.selected_lease_id,
            corrected_fields=body.corrected_fields,
            auth_context=auth,
            sr_id=body.sr_id,
        )
    except Exception as exc:
        bound_log.exception("api.chat.service_request.unhandled_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your request.  Please try again.",
        ) from exc

    return ServiceRequestChatResponse(
        session_id=str(result.session_id),
        active_agent=result.active_agent,
        message=result.message,
        ui=result.ui,
        draft_preview=result.draft_preview,
        faq_sources=result.faq_sources,
        state=ChatStatePayload(
            intent=result.state.intent,
            workflow_stage=result.state.workflow_stage,
            missing_fields=result.state.missing_fields,
            ready_to_submit=result.state.ready_to_submit,
        ),
        trace_id=str(result.trace_id) if result.trace_id else None,
    )


# ---------------------------------------------------------------------------
# Backward-compatible stub — POST /api/v1/chat/turn
# ---------------------------------------------------------------------------


class ChatTurnRequest(BaseModel):
    session_id: UUID | None = Field(
        default=None,
        description="Existing session; omit to start a new conversation.",
    )
    message: str = Field(min_length=1)


class ChatTurnResponse(BaseModel):
    session_id: UUID
    reply: str
    trace_id: UUID | None = None


@router.post(
    "/chat/turn",
    response_model=ChatTurnResponse,
    deprecated=True,
    summary="[Deprecated] Chat turn (v1 stub)",
    description="Use ``POST /api/chat/service-request`` instead.",
)
async def post_chat_turn(
    body: ChatTurnRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> ChatTurnResponse:
    """Backward-compatible stub — delegates to the new service-request endpoint."""
    _ = auth
    session_id = body.session_id or uuid4()
    return ChatTurnResponse(
        session_id=session_id,
        reply="Use POST /api/chat/service-request for full functionality.",
        trace_id=None,
    )
