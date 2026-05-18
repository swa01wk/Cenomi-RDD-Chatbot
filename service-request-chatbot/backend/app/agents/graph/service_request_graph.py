"""Compile the full LangGraph service-request workflow.

Graph shape
-----------
START
  → load_session
  → supervisor          (skipped when active_agent already set)
  → registry            (skipped when active_agent already set)
  → handover_entry      (HITL confirmation parser + workflow boundary)
  → field_extraction
  → merge_state
  → lease_lookup        (skipped when lease_id already in collected_data)
  → validation
  → missing_field       (when fields missing or blocking validation errors)
  → confirmation        (when all fields valid; pause for user confirmation)
  → payload_builder     (only when confirmation_status == CONFIRMED)
  → api_submission      (only when confirmation_status == CONFIRMED)
  → response_generation
  → save_state
  → END

Every user turn ends at save_state → END regardless of which path was taken.
State is persisted by save_state_node; it is reloaded at the start of the next
turn by load_session_node.  There is no LangGraph interrupt/resume — every turn
is a complete graph execution.

Routing functions
-----------------
All routing functions are pure — they read state, call no services or LLM,
and contain no side effects.  Business logic that belongs to a service lives
in the corresponding node, never here.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.nodes.api_submission_node import api_submission_node
from app.agents.graph.nodes.confirmation_node import confirmation_node
from app.agents.graph.nodes.field_extraction_node import field_extraction_node
from app.agents.graph.nodes.handover_entry_node import handover_entry_node
from app.agents.graph.nodes.lease_lookup_node import lease_lookup_node
from app.agents.graph.nodes.load_session_node import load_session_node
from app.agents.graph.nodes.merge_state_node import merge_state_node
from app.agents.graph.nodes.missing_field_node import missing_field_node
from app.agents.graph.nodes.payload_builder_node import payload_builder_node
from app.agents.graph.nodes.registry_node import registry_node
from app.agents.graph.nodes.response_generation_node import response_generation_node
from app.agents.graph.nodes.save_state_node import save_state_node
from app.agents.graph.nodes.supervisor_node import supervisor_node
from app.agents.graph.nodes.validation_node import validation_node
from app.agents.graph.state import ServiceRequestGraphState

# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_after_load(state: dict[str, Any]) -> str:
    """Skip supervisor + registry if a downstream agent is already active.

    An active_agent means a prior turn already classified the intent and
    resolved the agent via the registry.  Re-running those nodes every turn
    would make an unnecessary LLM call (supervisor) and is semantically wrong
    — the user is continuing an in-progress workflow, not starting a new one.

    Cancel / switch detection is handled inside handover_entry_node; if the
    user explicitly cancels, that node clears active_agent so the next turn
    re-enters through the supervisor.
    """
    return "handover_entry" if state.get("active_agent") else "supervisor"


def _route_after_supervisor(state: dict[str, Any]) -> str:
    """Continue to registry on successful classification; short-circuit otherwise."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "registry"


def _route_after_registry(state: dict[str, Any]) -> str:
    """Continue to handover pipeline on successful registry lookup."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "handover_entry"


def _route_after_merge(state: dict[str, Any]) -> str:
    """Run lease lookup when the lease is not yet resolved.

    Two cases trigger lease lookup:
    1. selected_lease is set — the user just picked from a multi-match list;
       lease_lookup_node merges it into collected_data (Path A in that node).
    2. lease_id is absent from collected_data — the lease has never been
       resolved; lease_lookup_node attempts a fresh API lookup (Path B).
    """
    if state.get("selected_lease"):
        return "lease_lookup"
    collected = state.get("collected_data") or {}
    if not collected.get("lease_id"):
        return "lease_lookup"
    return "validation"


def _route_after_lease(state: dict[str, Any]) -> str:
    """Pause when lease lookup needs user input (0 or N matches)."""
    if state.get("status") == "WAITING_FOR_USER":
        return "response_generation"
    return "validation"


def _route_after_validation(state: dict[str, Any]) -> str:
    """Route to missing_field when there is still work to do before confirmation.

    Priority order:
    1. Blocking validation errors (invalid data) → ask for correction.
    2. Missing required fields → ask next question.
    3. All clear → proceed to confirmation.

    get_missing_fields is a pure schema helper — it is safe to call in a
    routing function because it performs no I/O.
    """
    from app.agents.schemas.handover_schema import get_missing_fields  # local import avoids circular

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

    return "confirmation"


def _route_after_handover_entry(state: dict[str, Any]) -> str:
    """Route after the handover entry boundary node.

    Three paths:
    1. ``response_generation`` — workflow was just restarted (active_agent
       cleared); skip the data pipeline entirely for this turn.
    2. ``merge_state`` — current turn IS a UI cancel button (action_override=
       "cancel"); skip field_extraction so the raw "cancel" signal is never
       misinterpreted as a field value.
    3. ``field_extraction`` — all other turns, including:
       - Text-based rejections that may embed inline corrections
         (e.g. "change end date to 2026-08-05").  The extraction LLM returns
         {} for pure rejection phrases like "No", so this is safe.
       - Normal data-collection turns.
    """
    # Workflow restart: handover_entry cleared active_agent this turn and set
    # WAITING_FOR_USER.  handover_entry_node can only be reached when
    # active_agent was already set at load time, so active_agent becoming None
    # here exclusively means the restart handler fired — no additional
    # collected_data guard is needed (and would break when collected_data is
    # intentionally cleared to {} by the restart handler).
    if (
        state.get("active_agent") is None
        and state.get("status") == "WAITING_FOR_USER"
    ):
        return "response_generation"
    # UI cancel button only — skip extraction to avoid misinterpreting "cancel".
    if state.get("action_override") == "cancel":
        return "merge_state"
    return "field_extraction"


def _route_after_confirmation(state: dict[str, Any]) -> str:
    """Proceed to payload building only after explicit user confirmation."""
    if state.get("confirmation_status") == "CONFIRMED":
        return "payload_builder"
    return "response_generation"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_service_request_graph():
    """Build and compile the full service-request LangGraph.

    Returns a compiled ``CompiledGraph`` ready for ``ainvoke`` / ``astream``.
    Call ``get_compiled_graph()`` in production code to get the singleton.
    """
    graph = StateGraph(ServiceRequestGraphState)

    # ── Node registration ───────────────────────────────────────────────────
    graph.add_node("load_session", load_session_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("registry", registry_node)
    graph.add_node("handover_entry", handover_entry_node)
    graph.add_node("field_extraction", field_extraction_node)
    graph.add_node("merge_state", merge_state_node)
    graph.add_node("lease_lookup", lease_lookup_node)
    graph.add_node("validation", validation_node)
    graph.add_node("missing_field", missing_field_node)
    graph.add_node("confirmation", confirmation_node)
    graph.add_node("payload_builder", payload_builder_node)
    graph.add_node("api_submission", api_submission_node)
    graph.add_node("response_generation", response_generation_node)
    graph.add_node("save_state", save_state_node)

    # ── Entry point ─────────────────────────────────────────────────────────
    graph.add_edge(START, "load_session")

    # ── Session / intent routing ────────────────────────────────────────────
    graph.add_conditional_edges(
        "load_session",
        _route_after_load,
        {"supervisor": "supervisor", "handover_entry": "handover_entry"},
    )
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

    # ── Handover data pipeline ──────────────────────────────────────────────
    graph.add_conditional_edges(
        "handover_entry",
        _route_after_handover_entry,
        {
            "field_extraction": "field_extraction",
            "merge_state": "merge_state",
            "response_generation": "response_generation",
        },
    )
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

    # ── Validation → question / confirmation ────────────────────────────────
    graph.add_conditional_edges(
        "validation",
        _route_after_validation,
        {"missing_field": "missing_field", "confirmation": "confirmation"},
    )
    graph.add_edge("missing_field", "response_generation")

    graph.add_conditional_edges(
        "confirmation",
        _route_after_confirmation,
        {"payload_builder": "payload_builder", "response_generation": "response_generation"},
    )

    # ── Submission pipeline ─────────────────────────────────────────────────
    graph.add_edge("payload_builder", "api_submission")
    graph.add_edge("api_submission", "response_generation")

    # ── Turn finalisation — always runs ────────────────────────────────────
    graph.add_edge("response_generation", "save_state")
    graph.add_edge("save_state", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_compiled_graph = None


def get_compiled_graph():
    """Return the lazily-compiled singleton graph.

    Import and call this in the FastAPI lifespan or chat route handler.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_service_request_graph()
    return _compiled_graph
