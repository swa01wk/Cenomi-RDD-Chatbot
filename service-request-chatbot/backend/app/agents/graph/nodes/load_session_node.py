"""Load session + draft state from DB at the start of each graph turn.

Reads ``conversation_state_service`` from runtime state (injected by the API
layer before graph invocation).  Returns ``{}`` gracefully when the service is
absent or the session has no prior draft — first-turn behaviour is unaffected.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)


@trace_node("load_session", "CHAIN")
async def load_session_node(state: ServiceRequestState) -> dict[str, Any]:
    state_service = state.get("conversation_state_service")  # type: ignore[typeddict-item]
    if state_service is None:
        return {}

    session_id = state.get("session_id")
    if not session_id:
        return {}

    try:
        loaded: dict[str, Any] = await state_service.load(UUID(str(session_id)))
        if loaded:
            log.debug(
                "load_session_node.state_restored",
                session_id=session_id,
                keys=list(loaded.keys()),
            )
        # ``missing_fields`` is recomputed each turn by ``missing_field_node``
        # (and by ``_route_after_validation`` for routing purposes).  Carrying a
        # stale list across turns misleads ``field_extraction`` (which uses it as
        # an LLM hint) and ``response_generation`` (which includes it in the LLM
        # context).  Reset it here so every turn starts with an empty list.
        loaded.pop("missing_fields", None)
        return loaded
    except Exception:
        log.exception("load_session_node.failed", session_id=session_id)
        return {}
