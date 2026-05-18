"""Compile the full LangGraph service-request workflow.

Graph shape
-----------
START
  → load_session
  → sr_status_sync    (when sr_id present — syncs platform status)
  → supervisor          (skipped when active_agent already set)
  → registry            (skipped when active_agent already set)
  → handover_entry      (CREATE_SR — HITL confirmation parser + workflow boundary)
  → fm_review_entry     (FM_REVIEW stage boundary)
  → rdd_review_entry    (RDD_REVIEW stage boundary)
  → field_extraction
  → merge_state
  → lease_lookup        (skipped when lease_id already in collected_data)
  → validation
  → missing_field       (when fields missing or blocking validation errors)
  → confirmation        (CREATE_SR — pause for user confirmation)
  → fm_confirmation     (FM_REVIEW — pause for FM action)
  → rdd_confirmation    (RDD_REVIEW — pause for RDD action)
  → payload_builder     (CREATE_SR — builds POST payload)
  → fm_payload_builder  (FM_REVIEW — builds PATCH payload)
  → rdd_payload_builder (RDD_REVIEW — builds POST report payload)
  → api_submission      (CREATE_SR — POSTs to platform)
  → fm_api_submission   (FM_REVIEW — PATCHes to platform)
  → rdd_api_submission  (RDD_REVIEW — submits report to platform)
  → response_generation
  → save_state
  → END

Every user turn ends at save_state → END regardless of which path was taken.

Routing functions
-----------------
All routing functions are pure — they read state, call no services or LLM,
and contain no side effects.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.nodes.api_submission_node import api_submission_node
from app.agents.graph.nodes.confirmation_node import confirmation_node
from app.agents.graph.nodes.field_extraction_node import field_extraction_node
from app.agents.graph.nodes.fm_api_submission_node import fm_api_submission_node
from app.agents.graph.nodes.fm_payload_builder_node import fm_payload_builder_node
from app.agents.graph.nodes.fm_review_entry_node import fm_review_entry_node
from app.agents.graph.nodes.handover_entry_node import handover_entry_node
from app.agents.graph.nodes.lease_lookup_node import lease_lookup_node
from app.agents.graph.nodes.load_session_node import load_session_node
from app.agents.graph.nodes.merge_state_node import merge_state_node
from app.agents.graph.nodes.missing_field_node import missing_field_node
from app.agents.graph.nodes.payload_builder_node import payload_builder_node
from app.agents.graph.nodes.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.nodes.rdd_payload_builder_node import rdd_payload_builder_node
from app.agents.graph.nodes.rdd_review_entry_node import rdd_review_entry_node
from app.agents.graph.nodes.registry_node import registry_node
from app.agents.graph.nodes.response_generation_node import response_generation_node
from app.agents.graph.nodes.save_state_node import save_state_node
from app.agents.graph.nodes.sr_status_sync_node import sr_status_sync_node
from app.agents.graph.nodes.supervisor_node import supervisor_node
from app.agents.graph.nodes.validation_node import validation_node
from app.agents.graph.state import ServiceRequestGraphState

# ---------------------------------------------------------------------------
# Agent entry-node dispatch table
# ---------------------------------------------------------------------------

_AGENT_ENTRY_NODES: dict[str, str] = {
    "handover_service_request_agent": "handover_entry",
    # fm_review and rdd_review are stage-routed by workflow_stage after
    # sr_status_sync — not by active_agent key.
}

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_after_load(state: dict[str, Any]) -> str:
    """Route to sr_status_sync when an SR ID exists; otherwise skip to agent/supervisor."""
    sr_id = (state.get("backend_refs") or {}).get("sr_id")
    if sr_id:
        return "sr_status_sync"
    agent = state.get("active_agent")
    if agent:
        return _AGENT_ENTRY_NODES.get(agent, "supervisor")
    return "supervisor"


def _route_after_sync(state: dict[str, Any]) -> str:
    """After status sync, route to the correct stage entry node."""
    workflow_stage: str = state.get("workflow_stage") or "CREATE_SR"
    agent = state.get("active_agent")

    if workflow_stage == "FM_REVIEW":
        return "fm_review_entry"
    if workflow_stage == "RDD_REVIEW":
        return "rdd_review_entry"

    # CREATE_SR path — route by active_agent
    if agent:
        return _AGENT_ENTRY_NODES.get(agent, "handover_entry")
    return "supervisor"


def _route_after_supervisor(state: dict[str, Any]) -> str:
    """Continue to registry on successful classification; short-circuit otherwise."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "registry"


def _route_after_registry(state: dict[str, Any]) -> str:
    """Continue to the correct agent entry node."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    agent = state.get("active_agent")
    return _AGENT_ENTRY_NODES.get(agent or "", "handover_entry")


def _route_after_merge(state: dict[str, Any]) -> str:
    """Run lease lookup when the lease is not yet resolved."""
    if state.get("selected_lease"):
        return "lease_lookup"
    collected = state.get("collected_data") or {}
    if not collected.get("lease_id"):
        return "lease_lookup"
    return "validation"


def _route_after_lease(state: dict[str, Any]) -> str:
    """Pause when lease lookup needs user input."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "validation"


def _route_after_validation(state: dict[str, Any]) -> str:
    """Route to missing_field, or to the stage-appropriate confirmation node."""
    from app.agents.schemas.handover_schema import get_missing_fields

    blocking = [
        e for e in (state.get("validation_errors") or [])
        if e.get("blocking", True)
    ]
    if blocking:
        return "missing_field"

    stage = state.get("workflow_stage") or "CREATE_SR"
    collected = state.get("collected_data") or {}
    if get_missing_fields(stage, collected):
        return "missing_field"

    # All clear — route to stage-specific confirmation
    if stage == "FM_REVIEW":
        return "fm_confirmation"
    if stage == "RDD_REVIEW":
        return "rdd_confirmation"
    return "confirmation"


def _route_after_handover_entry(state: dict[str, Any]) -> str:
    """Route after the CREATE_SR handover entry boundary node.

    Three paths:
    1. ``response_generation`` — workflow restarted (active_agent cleared).
    2. ``merge_state``         — UI cancel action; skip field_extraction.
    3. ``field_extraction``    — all other turns.
    """
    if (
        state.get("active_agent") is None
        and state.get("status") == "WAITING_FOR_USER"
    ):
        return "response_generation"
    if state.get("action_override") == "cancel":
        return "merge_state"
    return "field_extraction"


def _route_after_fm_entry(state: dict[str, Any]) -> str:
    """Route after fm_review_entry.

    - WAITING_FOR_USER → response_generation (role denied / upload / cancel).
    - fm_action set    → skip extraction, go straight to merge_state.
    - Otherwise        → field_extraction (collect FM date fields).
    """
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    backend_refs = state.get("backend_refs") or {}
    if backend_refs.get("fm_action"):
        return "merge_state"
    return "field_extraction"


def _route_after_rdd_entry(state: dict[str, Any]) -> str:
    """Route after rdd_review_entry.

    - WAITING_FOR_USER → response_generation (role denied / upload / cancel).
    - rdd_action set   → skip extraction, go straight to merge_state.
    - Otherwise        → field_extraction.
    """
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    backend_refs = state.get("backend_refs") or {}
    if backend_refs.get("rdd_action"):
        return "merge_state"
    return "field_extraction"


def _route_after_confirmation(state: dict[str, Any]) -> str:
    """Proceed to CREATE_SR payload building after confirmation."""
    if state.get("confirmation_status") == "CONFIRMED":
        return "payload_builder"
    return "response_generation"


def _route_after_fm_confirmation(state: dict[str, Any]) -> str:
    """Proceed to FM payload builder after FM confirmation."""
    if state.get("confirmation_status") == "CONFIRMED":
        return "fm_payload_builder"
    return "response_generation"


def _route_after_rdd_confirmation(state: dict[str, Any]) -> str:
    """Proceed to RDD payload builder after RDD confirmation."""
    if state.get("confirmation_status") == "CONFIRMED":
        return "rdd_payload_builder"
    return "response_generation"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_service_request_graph():
    """Build and compile the full service-request LangGraph.

    Returns a compiled ``CompiledGraph`` ready for ``ainvoke`` / ``astream``.
    """
    graph = StateGraph(ServiceRequestGraphState)

    # ── Node registration ───────────────────────────────────────────────────
    graph.add_node("load_session", load_session_node)
    graph.add_node("sr_status_sync", sr_status_sync_node)
    graph.add_node("supervisor", supervisor_node)
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

    # ── Entry point ─────────────────────────────────────────────────────────
    graph.add_edge(START, "load_session")

    # ── Session / status-sync routing ───────────────────────────────────────
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

    # ── Intent routing ──────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {"registry": "registry", "response_generation": "response_generation"},
    )
    graph.add_conditional_edges(
        "registry",
        _route_after_registry,
        {"handover_entry": "handover_entry", "response_generation": "response_generation"},
    )

    # ── Stage entry nodes ────────────────────────────────────────────────────
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

    # ── Shared data pipeline ─────────────────────────────────────────────────
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

    # ── Validation → confirmation ────────────────────────────────────────────
    graph.add_conditional_edges(
        "validation",
        _route_after_validation,
        {
            "missing_field": "missing_field",
            "confirmation": "confirmation",
            "fm_confirmation": "fm_confirmation",
            "rdd_confirmation": "rdd_confirmation",
        },
    )
    graph.add_edge("missing_field", "response_generation")

    # ── Confirmation → payload builder ───────────────────────────────────────
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

    # ── Submission pipelines ─────────────────────────────────────────────────
    graph.add_edge("payload_builder", "api_submission")
    graph.add_edge("api_submission", "response_generation")
    graph.add_edge("fm_payload_builder", "fm_api_submission")
    graph.add_edge("fm_api_submission", "response_generation")
    graph.add_edge("rdd_payload_builder", "rdd_api_submission")
    graph.add_edge("rdd_api_submission", "response_generation")

    # ── Turn finalisation — always runs ─────────────────────────────────────
    graph.add_edge("response_generation", "save_state")
    graph.add_edge("save_state", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_compiled_graph = None


def get_compiled_graph():
    """Return the lazily-compiled singleton graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_service_request_graph()
    return _compiled_graph
