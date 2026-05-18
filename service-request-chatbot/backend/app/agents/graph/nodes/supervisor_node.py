"""Supervisor node — intent detection, classification, and agent routing.

Responsibilities
----------------
- Detect user intent by calling the LLM with the supervisor prompt.
- Classify the message into a ``SupervisorDecision`` (intent, confidence,
  service_category, sub_category, target_agent, reasoning).
- Maintain session continuity: if ``active_agent`` is already set in state,
  continue with it unless the user explicitly cancels or switches.
- Ask for clarification when confidence falls below ``CONFIDENCE_THRESHOLD``.
- Emit a trace run span and a detailed LLM-call record via ``TraceManager``.

Non-responsibilities (enforced)
--------------------------------
- MUST NOT collect, validate, or process form fields.
- MUST NOT submit or approve service requests.
- MUST NOT call downstream business APIs.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from app.agents.llm.gateway import LLMGateway, get_default_gateway
from app.agents.prompts.supervisor_prompt import (
    CONFIDENCE_THRESHOLD,
    SUPERVISOR_SYSTEM_PROMPT,
)
from app.agents.registries.service_request_registry import lookup_agent
from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Phrases that signal the user wants to restart or switch workflows
# ---------------------------------------------------------------------------

_CANCEL_PHRASES: frozenset[str] = frozenset(
    {
        "cancel",
        "start over",
        "restart",
        "different request",
        "nevermind",
        "never mind",
        "stop",
        "reset",
        "begin again",
        "new request",
    }
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _user_wants_to_switch(message: str) -> bool:
    """Return ``True`` if *message* contains an explicit cancel/switch phrase."""
    lowered = message.lower()
    return any(phrase in lowered for phrase in _CANCEL_PHRASES)


def _build_user_content(state: ServiceRequestState) -> str:
    """Build the user-facing content string sent to the LLM.

    Includes the current message plus lightweight context about the active
    session so the model can reason about continuity.
    """
    message = state.get("user_message") or ""
    parts = [f"User message: {message}"]

    active_agent = state.get("active_agent")
    if active_agent:
        parts.append(f"Currently active agent: {active_agent}")

    intent = state.get("intent")
    if intent:
        parts.append(f"Previously classified intent: {intent}")

    return "\n".join(parts)


async def _call_supervisor_llm(
    user_content: str,
    gateway: LLMGateway,
) -> tuple[SupervisorDecision, int, int, int]:
    """Call the LLM and parse the response as a ``SupervisorDecision``.

    Returns ``(decision, input_tokens, output_tokens, latency_ms)``.

    Raises
    ------
    json.JSONDecodeError
        If the model returns malformed JSON.
    pydantic.ValidationError
        If the JSON does not match ``SupervisorDecision``.
    openai.OpenAIError
        On transport / API errors.
    """
    parsed, input_tokens, output_tokens, latency_ms = await gateway.complete_json(
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        user_message=user_content,
    )
    decision = SupervisorDecision.model_validate(parsed)
    return decision, input_tokens, output_tokens, latency_ms


def _extract_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@trace_node("supervisor", "SUPERVISOR")
async def supervisor_node(state: ServiceRequestState) -> dict[str, Any]:  # noqa: C901
    """LangGraph node: classify intent and route to the appropriate downstream agent.

    The ``@trace_node`` decorator handles the outer node-level run span
    (BEFORE_NODE / AFTER_NODE snapshots + SUCCESS/FAILED finish).  This
    function additionally opens a child ``LLM`` run span for the LLM call
    itself so token counts and latency are captured separately.
    """
    user_message: str = state.get("user_message") or ""
    active_agent: str | None = state.get("active_agent")

    # Resolve trace plumbing from state (injected by TraceManager / lifespan).
    tm = state.get("trace_manager")
    trace_id: UUID | None = _extract_uuid(state.get("trace_id"))

    # ── 1. Session continuity ──────────────────────────────────────────────
    # If a downstream agent is already handling this session and the user has
    # not explicitly requested a switch, delegate back immediately.
    if active_agent and not _user_wants_to_switch(user_message):
        log.debug(
            "supervisor.session_continuity",
            active_agent=active_agent,
            user_message=user_message[:120],
        )
        return {"active_agent": active_agent}

    # ── 2. Open child LLM-call run span ───────────────────────────────────
    # ``_trace_node_run_id`` is injected by the ``@trace_node`` decorator
    # so the LLM span is nested under the supervisor node span in the run tree.
    node_run_id: UUID | None = _extract_uuid(state.get("_trace_node_run_id"))
    llm_run_id: UUID | None = None
    if tm is not None and trace_id is not None:
        try:
            llm_run_id = await tm.start_run(
                trace_id=trace_id,
                run_name="supervisor_llm_call",
                run_type="LLM",
                parent_run_id=node_run_id,
            )
        except Exception:
            log.warning("supervisor.start_llm_run.failed", exc_info=True)

    # ── 3. LLM classification ──────────────────────────────────────────────
    gateway = get_default_gateway()
    user_content = _build_user_content(state)

    decision: SupervisorDecision | None = None
    parse_success: bool = False
    parse_error: str | None = None
    input_tokens = output_tokens = latency_ms = 0
    llm_wall_start = time.monotonic()

    try:
        decision, input_tokens, output_tokens, latency_ms = await _call_supervisor_llm(
            user_content, gateway
        )
        parse_success = True
        log.info(
            "supervisor.llm_classified",
            intent=decision.intent,
            confidence=decision.confidence,
            target_agent=decision.target_agent,
            reasoning=decision.reasoning,
        )
    except json.JSONDecodeError as exc:
        parse_error = f"JSONDecodeError: {exc}"
        log.warning("supervisor.llm_json_parse_failed", error=parse_error)
    except Exception as exc:
        parse_error = str(exc)
        log.exception("supervisor.llm_call_failed", error=parse_error)

    # ── 4. Emit LLM call metadata ──────────────────────────────────────────
    if tm is not None and trace_id is not None and llm_run_id is not None:
        effective_latency = latency_ms or int((time.monotonic() - llm_wall_start) * 1000)
        try:
            await tm.capture_llm_call(
                trace_id=trace_id,
                run_id=llm_run_id,
                provider="openai",
                model=gateway.model,
                temperature=Decimal("0"),
                prompt_name="supervisor_prompt",
                prompt_version="1.0",
                input_tokens=input_tokens or None,
                output_tokens=output_tokens or None,
                total_tokens=(input_tokens + output_tokens) or None,
                latency_ms=effective_latency,
                structured_output=decision.model_dump() if decision else None,
                parse_success=parse_success,
                parse_error=parse_error,
            )
        except Exception:
            log.warning("supervisor.capture_llm_call.failed", exc_info=True)

        try:
            await tm.finish_run(
                run_id=llm_run_id,
                output=decision.model_dump() if decision else {"error": parse_error},
                status="SUCCESS" if parse_success else "FAILED",
                error_message=parse_error,
            )
        except Exception:
            log.warning("supervisor.finish_llm_run.failed", exc_info=True)

    # ── 5. Handle LLM/parse failure → graceful degradation ────────────────
    if decision is None:
        return {
            "response_message": (
                "The user's intent could not be determined due to an internal error. "
                "Politely ask them to rephrase what they'd like to do with their service request."
            ),
            "status": "WAITING_FOR_USER",
        }

    # ── 6. Low-confidence or UNKNOWN → ask clarification ──────────────────
    if decision.confidence < CONFIDENCE_THRESHOLD or decision.intent == "UNKNOWN":
        log.info(
            "supervisor.low_confidence_clarification",
            intent=decision.intent,
            confidence=decision.confidence,
        )
        return {
            "intent": decision.intent,
            "response_message": (
                "The intent is unclear. Ask the user to clarify whether they want to "
                "create, update, approve, or check the status of a service request. "
                "Be friendly and offer to guide them."
            ),
            "status": "WAITING_FOR_USER",
        }

    # ── 7. Registry validation ─────────────────────────────────────────────
    # Cross-check the LLM's routing against the authoritative registry so a
    # hallucinated agent name never propagates downstream.
    agent_config = None
    if decision.service_category and decision.sub_category:
        agent_config = lookup_agent(decision.service_category, decision.sub_category)

    if agent_config is None and decision.target_agent:
        # Log the gap but trust the LLM routing — the registry may not yet
        # contain all agents.  Registry node will validate further.
        log.warning(
            "supervisor.agent_not_in_registry",
            service_category=decision.service_category,
            sub_category=decision.sub_category,
            target_agent=decision.target_agent,
        )

    # ── 8. Route ───────────────────────────────────────────────────────────
    return {
        "intent": decision.intent,
        "service_category": decision.service_category,
        "sub_category": decision.sub_category,
        "active_agent": decision.target_agent,
        "status": "IN_PROGRESS",
    }
