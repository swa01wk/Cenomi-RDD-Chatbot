"""Persist draft state to DB at the end of each graph turn.

Reads ``conversation_state_service`` from runtime state (injected by the API
layer).  Returns ``{}`` gracefully when absent so the graph never fails due to
a missing persistence layer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)


@trace_node("save_state", "CHAIN")
async def save_state_node(state: ServiceRequestState) -> dict[str, Any]:
    state_service = state.get("conversation_state_service")  # type: ignore[typeddict-item]
    if state_service is None:
        return {}

    session_id = state.get("session_id")
    if not session_id:
        return {}

    try:
        await state_service.save_checkpoint(UUID(str(session_id)), dict(state))
        log.debug("save_state_node.ok", session_id=session_id)
    except Exception:
        log.exception("save_state_node.failed", session_id=session_id)

    return {}
