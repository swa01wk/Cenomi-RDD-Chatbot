"""Registry node — resolves and validates the target agent from the service registry.

This node runs after the supervisor has written ``service_category`` and
``sub_category`` into state.  It performs a definitive lookup against
``SERVICE_REQUEST_AGENT_REGISTRY`` and writes back the canonical
``active_agent`` (and implicitly validates the routing produced by the
supervisor LLM).

Responsibilities
----------------
- Look up ``(service_category, sub_category)`` in the registry.
- Detect and log any mismatch between the supervisor's ``active_agent`` and
  the registry's authoritative ``agent_name``.
- Surface a user-friendly message if no agent is registered for the routing.
- Emit a traced node span via ``@trace_node``.

Non-responsibilities
--------------------
- MUST NOT collect or validate form fields.
- MUST NOT make LLM calls.
- MUST NOT submit or approve requests.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.registries.service_request_registry import (
    SERVICE_REQUEST_AGENT_REGISTRY,  # re-exported for callers that import from here
    lookup_agent,
)
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

__all__ = [
    "registry_node",
    "SERVICE_REQUEST_AGENT_REGISTRY",
]


@trace_node("registry", "LANGGRAPH_NODE")
async def registry_node(state: ServiceRequestState) -> dict[str, Any]:
    """LangGraph node: validate routing against the service-request agent registry.

    Reads
    -----
    state["service_category"], state["sub_category"], state["active_agent"]

    Writes
    ------
    state["active_agent"]  — overwritten with the registry's canonical agent_name.
    state["status"]        — ``"IN_PROGRESS"`` on success, ``"WAITING_FOR_USER"``
                             when no agent is registered.
    state["response_message"] — set only when routing cannot be resolved.
    """
    service_category: str | None = state.get("service_category")
    sub_category: str | None = state.get("sub_category")
    supervisor_agent: str | None = state.get("active_agent")

    # ── 1. Guard: routing keys must be present ─────────────────────────────
    if not service_category or not sub_category:
        log.warning(
            "registry_node.missing_routing_keys",
            service_category=service_category,
            sub_category=sub_category,
        )
        return {
            "response_message": (
                "I couldn't determine which type of service request you need. "
                "Could you clarify what you'd like to do?"
            ),
            "status": "WAITING_FOR_USER",
        }

    # ── 2. Registry lookup ─────────────────────────────────────────────────
    agent_config = lookup_agent(service_category, sub_category)

    if agent_config is None:
        log.warning(
            "registry_node.agent_not_found",
            service_category=service_category,
            sub_category=sub_category,
        )
        return {
            "response_message": (
                f"I don't have a handler configured for "
                f"'{service_category} / {sub_category}' yet. "
                "Please contact support or try a different request."
            ),
            "status": "WAITING_FOR_USER",
        }

    resolved_agent = agent_config["agent_name"]

    # ── 3. Consistency check: supervisor vs registry ───────────────────────
    if supervisor_agent and supervisor_agent != resolved_agent:
        log.warning(
            "registry_node.agent_mismatch",
            supervisor_agent=supervisor_agent,
            registry_agent=resolved_agent,
            service_category=service_category,
            sub_category=sub_category,
        )
        # Registry is authoritative; override the supervisor's choice.

    log.info(
        "registry_node.resolved",
        agent_name=resolved_agent,
        display_name=agent_config["display_name"],
        schema_key=agent_config["schema_key"],
        service_category=service_category,
        sub_category=sub_category,
    )

    # ── 4. Write resolved routing back to state ────────────────────────────
    return {
        "active_agent": resolved_agent,
        "status": "IN_PROGRESS",
    }
