"""Compile the Helper Agent LangGraph — extends the SR workflow with a Q&A path.

Graph shape
-----------
START
  → load_session
  → sr_status_sync    (when sr_id present — syncs platform status)
  → supervisor        (skipped when active_agent already set)
  → faq_node          (NEW — Q&A path: ASK_HELP / UNKNOWN intents)
  → registry          (SR action intents: routes to the correct agent)
  → handover_entry    (CREATE_SR — HITL confirmation parser)
  → fm_review_entry   (FM_REVIEW stage boundary)
  → rdd_review_entry  (RDD_REVIEW stage boundary)
  → field_extraction
  → merge_state
  → lease_lookup
  → validation
  → missing_field
  → confirmation / fm_confirmation / rdd_confirmation
  → payload_builder / fm_payload_builder / rdd_payload_builder
  → api_submission / fm_api_submission / rdd_api_submission
  → response_generation
  → save_state
  → END

New additions vs. service_request_graph.py
-------------------------------------------
1. ``faq_node``  — LLM call with embedded FAQ prompt (no external search).
2. ``_route_after_supervisor``  — routes ASK_HELP / UNKNOWN → faq_node;
   SR action intents → registry; RBAC mismatch → response_generation.

RBAC enforcement
----------------
``_route_after_supervisor`` checks ``ROLE_PERMITTED_INTENTS`` against the
``auth_context`` stored in graph state.  If the classified intent is not
permitted for the user's role, the turn routes directly to
``response_generation`` with a denial message — no SR workflow is activated.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

# ── Shared infrastructure nodes ──────────────────────────────────────────────
from app.agents.graph.nodes.shared.load_session_node import load_session_node
from app.agents.graph.nodes.shared.save_state_node import save_state_node
# supervisor_node lives at nodes/ root for test-patching compatibility
from app.agents.graph.nodes.supervisor_node import _user_wants_preview, supervisor_node
from app.agents.graph.nodes.shared.registry_node import registry_node
from app.agents.graph.nodes.shared.sr_status_sync_node import sr_status_sync_node
from app.agents.graph.nodes.shared.response_generation_node import response_generation_node
from app.agents.registries.workflow_config import WORKFLOW_CONFIG_REGISTRY, get_workflow_config

# ── FAQ agent nodes ───────────────────────────────────────────────────────────
from app.agents.graph.nodes.faq.faq_node import faq_node

# ── Handover SR action agent nodes ────────────────────────────────────────────
from app.agents.graph.nodes.handover.handover_entry_node import handover_entry_node
from app.agents.graph.nodes.handover.fm_review_entry_node import fm_review_entry_node
from app.agents.graph.nodes.handover.rdd_review_entry_node import rdd_review_entry_node
from app.agents.graph.nodes.handover.field_extraction_node import field_extraction_node
from app.agents.graph.nodes.handover.merge_state_node import merge_state_node
from app.agents.graph.nodes.handover.lease_lookup_node import lease_lookup_node
from app.agents.graph.nodes.handover.validation_node import validation_node
from app.agents.graph.nodes.handover.missing_field_node import missing_field_node
from app.agents.graph.nodes.handover.confirmation_node import confirmation_node
from app.agents.graph.nodes.handover.preview_node import preview_node
from app.agents.graph.nodes.handover.payload_builder_node import payload_builder_node
from app.agents.graph.nodes.handover.fm_payload_builder_node import fm_payload_builder_node
from app.agents.graph.nodes.handover.rdd_payload_builder_node import rdd_payload_builder_node
from app.agents.graph.nodes.handover.api_submission_node import api_submission_node
from app.agents.graph.nodes.handover.fm_api_submission_node import fm_api_submission_node
from app.agents.graph.nodes.handover.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.state import ServiceRequestGraphState

# ---------------------------------------------------------------------------
# Agent entry-node dispatch table
# ---------------------------------------------------------------------------

_AGENT_ENTRY_NODES: dict[str, str] = {
    "handover_service_request_agent": "handover_entry",
}

# Intents that route to the FAQ node (Q&A path — no SR workflow activation)
_FAQ_INTENTS: frozenset[str] = frozenset({"ASK_HELP", "UNKNOWN"})

# Derived from all registered workflow configs — adding a new workflow auto-expands this set.
_SR_ACTION_INTENTS: frozenset[str] = frozenset(
    intent
    for cfg in WORKFLOW_CONFIG_REGISTRY.values()
    for intent in cfg.action_intents
)

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_after_load(state: dict[str, Any]) -> str:
    """Route to sr_status_sync when an SR ID exists; otherwise to agent/supervisor."""
    user_message = state.get("user_message") or ""
    if _user_wants_preview(user_message):
        return "supervisor"

    sr_id = (state.get("backend_refs") or {}).get("sr_id")
    if sr_id:
        return "sr_status_sync"

    agent = state.get("active_agent")
    if agent:
        return _AGENT_ENTRY_NODES.get(agent, "supervisor")
    return "supervisor"


def _route_after_sync(state: dict[str, Any]) -> str:
    """After status sync, route to the correct stage entry node.

    Routing is data-driven: each ``WorkflowConfig`` declares which
    ``workflow_stage`` values map to which graph nodes.  Adding a new workflow
    with new stage names requires only a registry entry — no code change here.
    """
    workflow_stage: str = state.get("workflow_stage") or ""
    agent: str = state.get("active_agent") or ""

    # 1. Per-workflow stage → entry node (keyed by active_agent)
    cfg = get_workflow_config(agent)
    if cfg and workflow_stage in cfg.stage_sync_nodes:
        return cfg.stage_sync_nodes[workflow_stage]

    # 2. Scan all configs when active_agent is not yet set
    for registered_cfg in WORKFLOW_CONFIG_REGISTRY.values():
        if workflow_stage in registered_cfg.stage_sync_nodes:
            return registered_cfg.stage_sync_nodes[workflow_stage]

    # 3. Terminal stages → supervisor for next intent
    all_terminal: frozenset[str] = frozenset(
        s for c in WORKFLOW_CONFIG_REGISTRY.values() for s in c.terminal_stages
    )
    if workflow_stage in all_terminal:
        return "supervisor"

    # 4. Fallback: active_agent entry node or supervisor
    if agent:
        return _AGENT_ENTRY_NODES.get(agent, "handover_entry")
    return "supervisor"


def _route_after_supervisor(state: dict[str, Any]) -> str:
    """Route after intent classification.

    Priority:
    1. PREVIEW_SERVICE_REQUEST → preview node.
    2. WAITING_FOR_USER (LLM/parse failure or RBAC denial set in supervisor_node)
       → response_generation.
    3. CHECK_SERVICE_REQUEST_STATUS → preview node.
    4. ASK_HELP / UNKNOWN → faq_node.
    5. SR action intents → registry.

    RBAC enforcement is performed inside supervisor_node (not here) so that the
    denial message is correctly propagated through graph state.  This function
    is intentionally side-effect-free and only reads state.
    """
    intent: str = state.get("intent") or "UNKNOWN"
    status: str = state.get("status") or ""

    # Preview always routes to the dedicated preview node
    if intent == "PREVIEW_SERVICE_REQUEST":
        return "preview"

    # LLM/parse failure or RBAC denial (supervisor_node sets WAITING_FOR_USER)
    if status == "WAITING_FOR_USER":
        return "response_generation"

    # CHECK_SERVICE_REQUEST_STATUS with sr_id → sr_status_sync already ran;
    # just show the SR via preview path
    if intent == "CHECK_SERVICE_REQUEST_STATUS":
        return "preview"

    # ── Q&A path ──────────────────────────────────────────────────────────────
    if intent in _FAQ_INTENTS:
        return "faq_node"

    # ── SR action path ────────────────────────────────────────────────────────
    if intent in _SR_ACTION_INTENTS:
        return "registry"

    # Fallback — unknown intent shape, send to FAQ
    return "faq_node"


def _route_after_registry(state: dict[str, Any]) -> str:
    """Continue to the correct agent entry node."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    agent = state.get("active_agent")
    return _AGENT_ENTRY_NODES.get(agent or "", "handover_entry")


def _route_after_merge(state: dict[str, Any]) -> str:
    if state.get("selected_lease"):
        return "lease_lookup"
    collected = state.get("collected_data") or {}
    if not collected.get("lease_id"):
        return "lease_lookup"
    return "validation"


def _route_after_lease(state: dict[str, Any]) -> str:
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "validation"


def _route_after_validation(state: dict[str, Any]) -> str:
    """Route after validation — data-driven via WorkflowConfig.

    Adding a new workflow with new collection stages and confirmation nodes
    requires only a registry entry — no code change here.
    """
    from app.agents.schemas.handover_schema import get_missing_fields

    blocking = [
        e for e in (state.get("validation_errors") or [])
        if e.get("blocking", True)
    ]
    if blocking:
        return "missing_field"

    original_stage = state.get("workflow_stage") or "CREATE_SR"
    active_agent: str = state.get("active_agent") or ""
    cfg = get_workflow_config(active_agent)

    # Resolve collection stages and confirmation nodes from WorkflowConfig.
    # Fall back to handover defaults when no config is found.
    collection_stages: frozenset[str] = (
        cfg.collection_stages
        if cfg
        else frozenset({"CREATE_SR", "FM_REVIEW", "RDD_REVIEW"})
    )
    confirmation_nodes: dict[str, str] = (
        cfg.confirmation_nodes
        if cfg
        else {"CREATE_SR": "confirmation", "FM_REVIEW": "fm_confirmation", "RDD_REVIEW": "rdd_confirmation"}
    )

    if original_stage not in collection_stages:
        return "response_generation"

    collected = state.get("collected_data") or {}
    if get_missing_fields(original_stage, collected):
        return "missing_field"

    return confirmation_nodes.get(original_stage, "confirmation")


def _route_after_handover_entry(state: dict[str, Any]) -> str:
    if (
        state.get("active_agent") is None
        and state.get("status") == "WAITING_FOR_USER"
    ):
        return "response_generation"
    if state.get("action_override") == "cancel":
        return "merge_state"
    return "field_extraction"


def _route_after_fm_entry(state: dict[str, Any]) -> str:
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    backend_refs = state.get("backend_refs") or {}
    if backend_refs.get("fm_action"):
        return "merge_state"
    return "field_extraction"


def _route_after_rdd_entry(state: dict[str, Any]) -> str:
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    backend_refs = state.get("backend_refs") or {}
    if backend_refs.get("rdd_action"):
        return "merge_state"
    return "field_extraction"


def _route_after_confirmation(state: dict[str, Any]) -> str:
    if state.get("confirmation_status") == "CONFIRMED":
        return "payload_builder"
    return "response_generation"


def _route_after_fm_confirmation(state: dict[str, Any]) -> str:
    if state.get("confirmation_status") == "CONFIRMED":
        return "fm_payload_builder"
    return "response_generation"


def _route_after_rdd_confirmation(state: dict[str, Any]) -> str:
    if state.get("confirmation_status") == "CONFIRMED":
        return "rdd_payload_builder"
    return "response_generation"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_helper_agent_graph():
    """Build and compile the full Helper Agent LangGraph.

    Extends the SR workflow graph with:
    - ``faq_node`` on the Q&A path (ASK_HELP / UNKNOWN intents)
    - Role-aware routing in ``_route_after_supervisor``
    """
    graph = StateGraph(ServiceRequestGraphState)

    # ── Node registration ────────────────────────────────────────────────────
    graph.add_node("load_session", load_session_node)
    graph.add_node("sr_status_sync", sr_status_sync_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("faq_node", faq_node)          # NEW
    graph.add_node("preview", preview_node)
    graph.add_node("registry", registry_node)
    graph.add_node("handover_entry", handover_entry_node)
    graph.add_node("fm_review_entry", fm_review_entry_node)
    graph.add_node("rdd_review_entry", rdd_review_entry_node)
    graph.add_node("field_extraction", field_extraction_node)
    graph.add_node("merge_state", merge_state_node)
    graph.add_node("lease_lookup", lease_lookup_node)
    graph.add_node("validation", validation_node)
    graph.add_node("missing_field", missing_field_node)
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("fm_confirmation", confirmation_node)
    graph.add_node("rdd_confirmation", confirmation_node)
    graph.add_node("payload_builder", payload_builder_node)
    graph.add_node("fm_payload_builder", fm_payload_builder_node)
    graph.add_node("rdd_payload_builder", rdd_payload_builder_node)
    graph.add_node("api_submission", api_submission_node)
    graph.add_node("fm_api_submission", fm_api_submission_node)
    graph.add_node("rdd_api_submission", rdd_api_submission_node)
    graph.add_node("response_generation", response_generation_node)
    graph.add_node("save_state", save_state_node)

    # ── Entry point ──────────────────────────────────────────────────────────
    graph.add_edge(START, "load_session")

    # ── Session / status-sync routing ────────────────────────────────────────
    graph.add_conditional_edges(
        "load_session",
        _route_after_load,
        {
            "sr_status_sync": "sr_status_sync",
            "supervisor": "supervisor",
            "handover_entry": "handover_entry",
        },
    )
    graph.add_conditional_edges(
        "sr_status_sync",
        _route_after_sync,
        {
            "handover_entry": "handover_entry",
            "fm_review_entry": "fm_review_entry",
            "rdd_review_entry": "rdd_review_entry",
            "supervisor": "supervisor",
        },
    )

    # ── Intent routing (NEW: faq_node added) ─────────────────────────────────
    graph.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "faq_node": "faq_node",
            "preview": "preview",
            "registry": "registry",
            "response_generation": "response_generation",
        },
    )
    graph.add_edge("faq_node", "response_generation")
    graph.add_edge("preview", "response_generation")
    graph.add_conditional_edges(
        "registry",
        _route_after_registry,
        {"handover_entry": "handover_entry", "response_generation": "response_generation"},
    )

    # ── Stage entry nodes ─────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "handover_entry",
        _route_after_handover_entry,
        {
            "field_extraction": "field_extraction",
            "merge_state": "merge_state",
            "response_generation": "response_generation",
        },
    )
    graph.add_conditional_edges(
        "fm_review_entry",
        _route_after_fm_entry,
        {
            "field_extraction": "field_extraction",
            "merge_state": "merge_state",
            "response_generation": "response_generation",
        },
    )
    graph.add_conditional_edges(
        "rdd_review_entry",
        _route_after_rdd_entry,
        {
            "field_extraction": "field_extraction",
            "merge_state": "merge_state",
            "response_generation": "response_generation",
        },
    )

    # ── Shared data pipeline ──────────────────────────────────────────────────
    graph.add_edge("field_extraction", "merge_state")
    graph.add_conditional_edges(
        "merge_state",
        _route_after_merge,
        {"lease_lookup": "lease_lookup", "validation": "validation"},
    )
    graph.add_conditional_edges(
        "lease_lookup",
        _route_after_lease,
        {"validation": "validation", "response_generation": "response_generation"},
    )

    # ── Validation → confirmation ─────────────────────────────────────────────
    graph.add_conditional_edges(
        "validation",
        _route_after_validation,
        {
            "missing_field": "missing_field",
            "confirmation": "confirmation",
            "fm_confirmation": "fm_confirmation",
            "rdd_confirmation": "rdd_confirmation",
            "response_generation": "response_generation",
        },
    )
    graph.add_edge("missing_field", "response_generation")

    # ── Confirmation → payload builder ────────────────────────────────────────
    graph.add_conditional_edges(
        "confirmation",
        _route_after_confirmation,
        {"payload_builder": "payload_builder", "response_generation": "response_generation"},
    )
    graph.add_conditional_edges(
        "fm_confirmation",
        _route_after_fm_confirmation,
        {"fm_payload_builder": "fm_payload_builder", "response_generation": "response_generation"},
    )
    graph.add_conditional_edges(
        "rdd_confirmation",
        _route_after_rdd_confirmation,
        {
            "rdd_payload_builder": "rdd_payload_builder",
            "response_generation": "response_generation",
        },
    )

    # ── Submission pipelines ──────────────────────────────────────────────────
    graph.add_edge("payload_builder", "api_submission")
    graph.add_edge("api_submission", "response_generation")
    graph.add_edge("fm_payload_builder", "fm_api_submission")
    graph.add_edge("fm_api_submission", "response_generation")
    graph.add_edge("rdd_payload_builder", "rdd_api_submission")
    graph.add_edge("rdd_api_submission", "response_generation")

    # ── Turn finalisation — always runs ───────────────────────────────────────
    graph.add_edge("response_generation", "save_state")
    graph.add_edge("save_state", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_compiled_helper_graph = None


def get_compiled_helper_graph():
    """Return the lazily-compiled singleton Helper Agent graph."""
    global _compiled_helper_graph
    if _compiled_helper_graph is None:
        _compiled_helper_graph = build_helper_agent_graph()
    return _compiled_helper_graph
