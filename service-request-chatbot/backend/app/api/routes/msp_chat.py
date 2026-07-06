"""MSP Platform-compatible help chat endpoints.

Exposes two routes that match the ``cenomi-ai-backend`` API contract so the
MSP Platform frontend can route help/FAQ traffic directly to this service:

    POST /api/v1/chat         — synchronous JSON response
    POST /api/v1/chat/stream  — SSE streaming response

Both routes are thin adapters over ``ChatOrchestrationService``.  They accept
the MSP request shape, delegate to the same LangGraph pipeline used by the
existing ``POST /api/chat/service-request`` endpoint, and map the result back
to the MSP response shapes:

    MSP request  : {message, conversation_id?, language?, context?}
    MSP response : {conversation_id, message_id, message, sources, language}
    SSE events   : token → source(s) → done  (error on failure)

Auth
----
``x-internal-api-token`` header is validated against ``settings.msp_service_token``
when that setting is configured.  When absent (default / shadow mode) the check
is skipped — consistent with ``RBAC_ENFORCE=false``.

``Authorization: Bearer <token>`` is processed by the existing ``get_auth_context``
dependency (same JWT flow as the existing endpoint).

Phase notes
-----------
Phase 1 (this file): pseudo-streaming — the full message is emitted as a single
``token`` SSE event after the graph returns.  True token-level streaming requires
LLM gateway changes and is deferred.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_auth_context
from app.db.session import DbSession
from app.services.chat_orchestration_service import (
    ChatOrchestrationService,
    ChatTurnResult,
    parse_session_id,
)
from app.types.chat import AuthContext

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

msp_chat_router = APIRouter(tags=["msp-chat"])

# ---------------------------------------------------------------------------
# Language detection helper (shared with faq_node — kept local to avoid
# circular imports; faq_node imports from this module would be wrong direction)
# ---------------------------------------------------------------------------

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")


def _detect_language(text: str) -> str:
    """Return ``"ar"`` when text contains Arabic script, otherwise ``"en"``."""
    return "ar" if _ARABIC_RE.search(text) else "en"


# ---------------------------------------------------------------------------
# Auth dependency — inbound service token
# ---------------------------------------------------------------------------


async def _require_service_token(
    x_internal_api_token: str | None = Header(default=None),
) -> None:
    """Validate the MSP service-key header when ``MSP_SERVICE_TOKEN`` is set.

    Shadow mode (token not configured): always passes through.
    Enforce mode (token configured): rejects mismatched or absent tokens.
    """
    expected = settings.msp_service_token
    if expected and x_internal_api_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing x-internal-api-token.",
        )


# ---------------------------------------------------------------------------
# Pydantic models — MSP contract
# ---------------------------------------------------------------------------


class _MSPChatContext(BaseModel):
    """Optional page-aware context sent by the MSP frontend widget."""

    current_url_pattern: str | None = Field(
        default=None,
        description="Current page URL pattern, e.g. '/servicerequest'.",
        examples=["/servicerequest"],
    )
    help_category: str | None = Field(
        default=None,
        description="Top-level help category, e.g. 'Service Requests'.",
        examples=["Service Requests"],
    )
    help_subcategory: str | None = Field(
        default=None,
        description="Help subcategory, e.g. 'How to Submit'.",
        examples=["How to Submit"],
    )


class MSPChatRequest(BaseModel):
    """Incoming MSP help chat request — matches ``cenomi-ai-backend`` ChatRequest."""

    message: str = Field(
        min_length=1,
        max_length=4000,
        description="User's natural-language question.",
        examples=["How do I submit a service request?"],
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Opaque conversation/session ID.  "
            "Omit on the first turn; include on subsequent turns for multi-turn context."
        ),
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    language: str | None = Field(
        default=None,
        description="Preferred response language: 'en' or 'ar'.  Auto-detected when omitted.",
        examples=["en", "ar"],
        pattern=r"^(en|ar)$",
    )
    context: _MSPChatContext | None = Field(
        default=None,
        description="Optional page-context hint for RAG filtering.",
    )


class Source(BaseModel):
    """A single RAG citation — matches ``cenomi-ai-backend`` Source dataclass."""

    source_type: str = Field(
        description="Knowledge-base origin type.",
        examples=["help_content", "user_guide", "mall_info", "key_contact", "event"],
    )
    title: str = Field(
        description="Document title / file ID from the indexer.",
        examples=["help_content_42_en_chunk0"],
    )


class MSPChatResponse(BaseModel):
    """Sync response envelope — matches ``cenomi-ai-backend`` ChatResponse."""

    conversation_id: str = Field(
        description="Session / conversation ID.  Reuse on the next turn."
    )
    message_id: str = Field(description="Per-message UUID for observability.")
    message: str = Field(description="Assistant reply text.")
    sources: list[Source] = Field(
        default_factory=list,
        description="RAG citations.  Empty when no relevant KB results were found.",
    )
    language: str = Field(
        description="Detected or requested language code.",
        examples=["en", "ar"],
    )


# ---------------------------------------------------------------------------
# Shared orchestration helper
# ---------------------------------------------------------------------------


async def _run_turn(
    body: MSPChatRequest,
    db: DbSession,
    auth: AuthContext,
) -> ChatTurnResult:
    """Resolve session and invoke the help-agent graph for one turn."""
    session_uuid = parse_session_id(body.conversation_id)

    # Derive a stable user identity from the JWT subject; fall back to a
    # deterministic stub when auth is anonymous (shadow mode).
    from app.services.chat_orchestration_service import user_id_to_uuid

    user_id = user_id_to_uuid(
        auth.subject_id
        if auth.subject_id not in ("anonymous", "unauthenticated")
        else "msp_anonymous"
    )

    msp_context: dict[str, Any] | None = None
    if body.context:
        msp_context = body.context.model_dump(exclude_none=True)

    service = ChatOrchestrationService(db)
    return await service.process_turn(
        session_id=session_uuid,
        user_id=user_id,
        message=body.message,
        attachments=[],
        auth_context=auth,
        language=body.language,
        msp_context=msp_context,
    )


# ---------------------------------------------------------------------------
# POST /chat  — synchronous JSON
# ---------------------------------------------------------------------------


@msp_chat_router.post(
    "/chat",
    response_model=MSPChatResponse,
    summary="Help agent — sync response",
    description=(
        "Submit a help/FAQ question to the help agent and receive a synchronous JSON "
        "response.  Maps to ``POST /api/v1/chat`` in the MSP Platform contract."
    ),
    dependencies=[Depends(_require_service_token)],
    responses={
        status.HTTP_200_OK: {"description": "Turn processed successfully."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid or missing service token / JWT."},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "Request validation failed."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"description": "Graph or persistence error."},
    },
)
async def post_msp_chat(
    body: MSPChatRequest,
    db: DbSession,
    auth: AuthContext = Depends(get_auth_context),
) -> MSPChatResponse:
    """Handle one synchronous help-chat turn."""
    bound_log = log.bind(
        subject=auth.subject_id,
        conversation_id=body.conversation_id,
        language=body.language,
    )
    bound_log.info("msp_chat.sync.received")

    try:
        result = await _run_turn(body, db, auth)
    except HTTPException:
        raise
    except Exception as exc:
        bound_log.exception("msp_chat.sync.error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your request. Please try again.",
        ) from exc

    lang = body.language or _detect_language(result.message)
    sources = [Source(**s) for s in result.faq_sources]
    message_id = str(uuid4())

    bound_log.info(
        "msp_chat.sync.completed",
        conversation_id=str(result.session_id),
        sources_count=len(sources),
        language=lang,
    )

    return MSPChatResponse(
        conversation_id=str(result.session_id),
        message_id=message_id,
        message=result.message,
        sources=sources,
        language=lang,
    )


# ---------------------------------------------------------------------------
# POST /chat/stream  — SSE streaming
# ---------------------------------------------------------------------------


@msp_chat_router.post(
    "/chat/stream",
    summary="Help agent — SSE streaming response",
    description=(
        "Submit a help/FAQ question and receive a Server-Sent Events stream.  "
        "Maps to ``POST /api/v1/chat/stream`` in the MSP Platform contract.  "
        "Phase 1: full message emitted as a single ``token`` event; true "
        "token-level streaming is deferred to LLM gateway work."
    ),
    dependencies=[Depends(_require_service_token)],
    responses={
        status.HTTP_200_OK: {
            "content": {"text/event-stream": {}},
            "description": "SSE stream: token → source(s) → done.",
        },
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid or missing service token / JWT."},
    },
)
async def post_msp_chat_stream(
    body: MSPChatRequest,
    db: DbSession,
    auth: AuthContext = Depends(get_auth_context),
) -> StreamingResponse:
    """Handle one streaming help-chat turn via SSE."""
    bound_log = log.bind(
        subject=auth.subject_id,
        conversation_id=body.conversation_id,
    )
    bound_log.info("msp_chat.stream.received")

    async def _generate() -> AsyncIterator[str]:
        try:
            result = await _run_turn(body, db, auth)
        except HTTPException as exc:
            # Re-surface FastAPI auth errors as an SSE error event so the
            # frontend's SSE parser sees a clean error rather than a broken stream.
            yield _sse("error", {"message": exc.detail})
            return
        except Exception as exc:
            log.exception("msp_chat.stream.graph_error", error=str(exc))
            yield _sse("error", {"message": "An error occurred while processing your request."})
            return

        lang = body.language or _detect_language(result.message)
        message_id = str(uuid4())
        conversation_id = str(result.session_id)

        # ── token event — full message as one chunk (Phase 1 pseudo-streaming) ─
        yield _sse("token", {"text": result.message})

        # ── source events — one per RAG citation ──────────────────────────────
        for source in result.faq_sources:
            yield _sse("source", source)

        # ── done event ────────────────────────────────────────────────────────
        yield _sse(
            "done",
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "language": lang,
            },
        )

        bound_log.info(
            "msp_chat.stream.completed",
            conversation_id=conversation_id,
            sources_count=len(result.faq_sources),
            language=lang,
        )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# SSE formatting helper
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE message frame.

    Output format (RFC 6202 / W3C EventSource):
        event: <type>\\n
        data: <json>\\n
        \\n
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
