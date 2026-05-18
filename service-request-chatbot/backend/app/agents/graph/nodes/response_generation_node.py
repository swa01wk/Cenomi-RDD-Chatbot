"""LLM-driven response generation node.

Every graph path converges here before save_state → END.

Responsibilities
----------------
- Call the LLM with full workflow context to produce a natural, personalised
  assistant message.
- Preserve structured ``response_ui`` payloads set by prior nodes unchanged
  (confirmation cards, lease selection lists, etc.); only the text ``message``
  field inside them is overwritten with the LLM output.
- Fall back gracefully to the raw ``response_message`` hint when the LLM call
  fails so the turn always completes.
- Force ``status = "WAITING_FOR_USER"`` for all non-terminal paths.

Non-responsibilities
--------------------
- Does not route or make workflow decisions.
- Does not modify ``collected_data`` or any domain fields.
- Does not submit or approve service requests.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.llm.gateway import get_default_gateway
from app.agents.prompts.response_generation_prompt import (
    RESPONSE_GENERATION_SYSTEM_PROMPT,
    build_response_generation_context,
)
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)

_FALLBACK_RESPONSE = (
    "I'm processing your request. Please wait a moment or provide more details."
)

# Terminal statuses whose ``response_message`` must not be overwritten.
_TERMINAL_STATUSES = {"SUBMITTED", "FAILED", "COMPLETED"}


@trace_node("response_generation", "AGENT")
async def response_generation_node(state: ServiceRequestState) -> dict[str, Any]:
    """Generate a natural LLM response and mark the turn as WAITING_FOR_USER."""

    current_message: str | None = state.get("response_message")
    current_status: str | None = state.get("status")
    current_ui: dict[str, Any] | None = state.get("response_ui")

    # Terminal paths: submission success/failure — use the message as-is but
    # still attempt LLM rewrite for a warmer tone.
    is_terminal = current_status in _TERMINAL_STATUSES

    # ── Build context for the LLM ───────────────────────────────────────────
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    missing_fields: list[str] = state.get("missing_fields") or []
    validation_errors: list[dict] = state.get("validation_errors") or []
    conversation_history: list[dict] = state.get("conversation_history") or []  # type: ignore[typeddict-item]
    user_message: str = state.get("user_message") or ""

    response_intent = current_message or _FALLBACK_RESPONSE

    user_content = build_response_generation_context(
        user_message=user_message,
        response_intent=response_intent,
        workflow_stage=state.get("workflow_stage"),
        intent=state.get("intent"),
        collected_data=collected_data,
        missing_fields=missing_fields,
        validation_errors=validation_errors,
        confirmation_status=state.get("confirmation_status"),
        response_ui_type=current_ui.get("type") if current_ui else None,
        conversation_history=conversation_history,
    )

    # ── Call the LLM ────────────────────────────────────────────────────────
    llm_message: str | None = None
    try:
        gateway = get_default_gateway()
        parsed, _, _, _ = await gateway.complete_json(
            system_prompt=RESPONSE_GENERATION_SYSTEM_PROMPT,
            user_message=user_content,
        )
        llm_message = parsed.get("message") or None
        if llm_message:
            logger.debug("response_generation_node.llm_success", preview=llm_message[:80])
        else:
            logger.warning("response_generation_node.llm_empty_message", raw=parsed)
    except json.JSONDecodeError as exc:
        logger.warning("response_generation_node.llm_json_parse_failed", error=str(exc))
    except Exception as exc:
        logger.warning("response_generation_node.llm_call_failed", error=str(exc))

    # Fall back to the raw hint from prior nodes if LLM failed or returned nothing.
    final_message = llm_message or response_intent or _FALLBACK_RESPONSE

    # ── Merge LLM message into structured UI when present ───────────────────
    updated_ui: dict[str, Any] | None = None
    if current_ui:
        updated_ui = {**current_ui, "message": final_message}

    # ── Build output ────────────────────────────────────────────────────────
    updates: dict[str, Any] = {"response_message": final_message}

    if updated_ui is not None:
        updates["response_ui"] = updated_ui

    # Preserve terminal statuses; set WAITING_FOR_USER for all other paths.
    if not is_terminal:
        updates["status"] = "WAITING_FOR_USER"

    return updates
