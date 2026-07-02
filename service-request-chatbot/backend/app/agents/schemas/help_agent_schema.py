"""Help Agent schema — role-to-intent permissions and supervisor decision model.

This module defines:
  ROLE_PERMITTED_INTENTS    — which supervisor intents each role is allowed to trigger.
  HelpAgentSupervisorDecision — extended supervisor output with ASK_HELP intent.
  intents_for_roles()       — helper to resolve permitted intents for an AuthContext.

Agent taxonomy
--------------
- help_agent  : supervisor classification + FAQ Q&A
- rdd_agent   : full RDD lifecycle (CREATE_SR → FM_REVIEW → RDD_REVIEW)

Design principle
----------------
Read intents (ASK_HELP, CHECK_STATUS, PREVIEW) are available to every role —
all stakeholders can ask questions and check SR status at any point in the lifecycle.
Action intents (CREATE_RDD_SR, APPROVE_RDD_SR, etc.) are role-restricted.

The DD_ENGINEER's RDD review action is triggered by ``sr_status_sync`` detecting
``DD_ENGINEER IN_PROGRESS``, NOT by a supervisor intent, so they only need
the read intent set here.
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared read intents — available to every authenticated role
# ---------------------------------------------------------------------------

_SR_READ_INTENTS: frozenset[str] = frozenset(
    {
        "ASK_HELP",
        "CHECK_SERVICE_REQUEST_STATUS",
        "PREVIEW_SERVICE_REQUEST",
        "UNKNOWN",
    }
)

# ALL_INTENTS is derived from the WorkflowConfig registry so new workflows
# automatically extend what the ADMIN role can use.
def _build_all_intents() -> frozenset[str]:
    from app.agents.registries.workflow_config import WORKFLOW_CONFIG_REGISTRY
    return frozenset(
        intent
        for cfg in WORKFLOW_CONFIG_REGISTRY.values()
        for intent in cfg.action_intents
    ) | _SR_READ_INTENTS


ALL_INTENTS: frozenset[str] = _build_all_intents()

# ---------------------------------------------------------------------------
# Role → permitted intents
# ---------------------------------------------------------------------------

ROLE_PERMITTED_INTENTS: dict[str, frozenset[str]] = {
    # Phase 1 actor — can create/update RDD SRs and create work permit SRs
    "MALL_MANAGER": _SR_READ_INTENTS
    | frozenset(
        {
            "CREATE_RDD_SERVICE_REQUEST",
            "UPDATE_RDD_SERVICE_REQUEST",
            "CREATE_WORK_PERMIT_SR",
        }
    ),
    # Phase 2 actor — can approve / save FM review
    "FM_MANAGER": _SR_READ_INTENTS
    | frozenset(
        {
            "APPROVE_RDD_SERVICE_REQUEST",
        }
    ),
    # Phase 2 support — same FM review actions as FM_MANAGER
    "OPERATIONS": _SR_READ_INTENTS
    | frozenset(
        {
            "APPROVE_RDD_SERVICE_REQUEST",
        }
    ),
    # Phase 3 actor — RDD review is triggered by sr_status_sync, not supervisor intent
    "DD_ENGINEER": _SR_READ_INTENTS,
    # Unrestricted
    "ADMIN": ALL_INTENTS,
}


def _rebuild_intents_for_roles() -> None:
    """Rebuild ALL_INTENTS and ADMIN's permitted intents after registry changes.

    Call this after registering additional workflows at runtime so that the
    ADMIN role's intent set stays in sync with the registry.
    """
    global ALL_INTENTS
    ALL_INTENTS = _build_all_intents()
    ROLE_PERMITTED_INTENTS["ADMIN"] = ALL_INTENTS


def intents_for_roles(roles: frozenset[str], is_global_admin: bool = False) -> frozenset[str]:
    """Return the union of permitted intents for a set of roles.

    Falls back to read-only intents when the role is unknown,
    rather than blocking the user entirely.
    """
    if is_global_admin:
        return ALL_INTENTS
    permitted: set[str] = set()
    for role in roles:
        permitted |= ROLE_PERMITTED_INTENTS.get(role, _SR_READ_INTENTS)
    return frozenset(permitted) if permitted else _SR_READ_INTENTS


# ---------------------------------------------------------------------------
# Extended supervisor decision schema
# ---------------------------------------------------------------------------

# HelpAgentIntent is a plain string so adding new workflow intents (e.g.
# "CREATE_RCD_SERVICE_REQUEST") never requires a type-annotation change here.
# Intent validation is enforced by RBAC (ROLE_PERMITTED_INTENTS) and the
# agent registry, not by the Python type system.
HelpAgentIntent = str


class HelpAgentSupervisorDecision(BaseModel):
    """LLM output for the Help Agent supervisor node.

    ``intent`` drives top-level routing:
      - ASK_HELP / UNKNOWN → faq_node
      - CREATE / UPDATE / APPROVE RDD SR intents → registry → stage entry node
      - CHECK_STATUS / PREVIEW → preview_node (via sr_status_sync)

    ``service_category`` and ``sub_category`` are only meaningful for SR action
    intents and are used by the registry for agent lookup.
    """

    intent: HelpAgentIntent
    service_category: str | None = None
    sub_category: str | None = None
    confidence: float = 1.0
    reasoning: str = ""
