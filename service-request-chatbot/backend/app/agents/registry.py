"""Service Request Agent Registry.

Maps ``(service_category, sub_category)`` pairs to the agent configuration
that should handle the corresponding workflow.  This is the single source of
truth for agent routing; supervisor and registry nodes must both consult it.

Adding a new service type requires only:
1. Inserting a new entry here.
2. Implementing the corresponding agent node.
"""

from __future__ import annotations

from typing import TypedDict


class AgentConfig(TypedDict):
    """Configuration record for a single registered agent."""

    agent_name: str
    """Canonical snake_case identifier used as the ``active_agent`` state key."""

    display_name: str
    """Human-readable name for logging and UI display."""

    schema_key: str
    """Key that downstream nodes use to resolve the correct field/stage schema."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SERVICE_REQUEST_AGENT_REGISTRY: dict[str, dict[str, AgentConfig]] = {
    "FIT_OUT_AND_HANDOVER": {
        "HANDOVER": {
            "agent_name": "handover_service_request_agent",
            "display_name": "Handover Service Request Agent",
            "schema_key": "handover_service_request_schema",
        },
    },
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def lookup_agent(service_category: str, sub_category: str) -> AgentConfig | None:
    """Return the ``AgentConfig`` for the given routing keys, or ``None``.

    Lookup is case-sensitive; callers must normalise the keys before calling.
    """
    return (
        SERVICE_REQUEST_AGENT_REGISTRY
        .get(service_category or "", {})
        .get(sub_category or "")
    )


def list_registered_agents() -> list[AgentConfig]:
    """Return a flat list of every ``AgentConfig`` in the registry."""
    return [
        agent_cfg
        for sub_map in SERVICE_REQUEST_AGENT_REGISTRY.values()
        for agent_cfg in sub_map.values()
    ]


def is_registered(service_category: str, sub_category: str) -> bool:
    """Return ``True`` if the pair has an entry in the registry."""
    return lookup_agent(service_category, sub_category) is not None
