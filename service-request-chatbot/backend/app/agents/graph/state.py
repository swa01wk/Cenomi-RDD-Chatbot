"""LangGraph graph state for the Service Request workflow.

``ServiceRequestGraphState`` is the single, authoritative state TypedDict that
every node reads from and writes partial updates back into.  All fields are
``total=False`` so LangGraph can merge incremental node outputs correctly;
required vs. optional semantics are enforced by the nodes / validators, not by
the TypedDict itself.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class ServiceRequestGraphState(TypedDict, total=False):
    """Canonical LangGraph state for a service-request conversation turn."""

    # ── Session / identity ────────────────────────────────────────────────────
    session_id: str
    user_id: str
    user_message: str
    attachments: list[dict]
    trace_id: str
    # Recent chat history injected by the orchestration layer: list of
    # {"role": "user"|"assistant", "content": "..."} dicts, oldest first.
    conversation_history: list[dict]

    # ── Routing / intent ──────────────────────────────────────────────────────
    active_agent: Optional[str]
    intent: Optional[str]
    service_category: Optional[str]
    sub_category: Optional[str]
    workflow_stage: Optional[str]

    # ── Collected / extracted data ────────────────────────────────────────────
    collected_data: dict[str, Any]
    extracted_fields: dict[str, Any]
    missing_fields: list[str]

    # ── Lease resolution ──────────────────────────────────────────────────────
    lease_matches: list[dict]
    selected_lease: Optional[dict]

    # ── Document handling ─────────────────────────────────────────────────────
    documents: list[dict]

    # ── Human-in-the-loop confirmation ────────────────────────────────────────
    confirmation_required: bool
    confirmation_status: Optional[Literal["PENDING", "CONFIRMED", "REJECTED"]]

    # ── Backend integration ───────────────────────────────────────────────────
    backend_refs: dict[str, Any]

    # ── Validation ────────────────────────────────────────────────────────────
    validation_errors: list[dict]

    # ── Response construction ─────────────────────────────────────────────────
    response_message: str
    response_ui: dict[str, Any]

    # ── Overall turn status ───────────────────────────────────────────────────
    status: Literal[
        "IN_PROGRESS",
        "WAITING_FOR_USER",
        "READY_TO_SUBMIT",
        "SUBMITTED",
        "COMPLETED",
        "FAILED",
    ]

    # ── UI-layer overrides (injected by the API layer, not persisted) ────────
    # When the frontend sends an explicit action ("confirm" / "cancel") or
    # inline-edited field values, these are injected into initial_state and
    # consumed by handover_entry_node / merge_state_node respectively.
    # They are intentionally NOT saved to the DB by save_state_node.
    action_override: Optional[str]           # "confirm" | "cancel" | None
    corrected_fields: Optional[dict]         # inline edits from confirmation card

    # ── Runtime-injected services (not serialisable; never checkpointed) ──────
    # LangGraph v0.2 only propagates keys that are declared as TypedDict fields.
    # These objects are injected by ChatOrchestrationService via initial_state
    # and must be listed here so that save_state_node / load_session_node (and
    # the tracing helpers in other nodes) can read them from graph state.
    conversation_state_service: Any  # ConversationStateService instance
    trace_manager: Any               # TraceManager instance


# Backward-compatible alias — existing node files import ServiceRequestState.
ServiceRequestState = ServiceRequestGraphState
