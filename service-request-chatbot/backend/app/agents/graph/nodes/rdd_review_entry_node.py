"""Entry boundary for the RDD_REVIEW workflow stage.

Responsibilities
----------------
- Validate that the caller has the DD_ENGINEER role.
- Handle ``action_override`` values specific to RDD_REVIEW:
    - ``submit_rdd_report`` → set ``backend_refs["rdd_action"] = "submit"``
    - ``cancel_update``     → reset to response_generation
    - ``upload_document``   → short-circuit (handled by upload route)
- Fall through to shared field_extraction pipeline when no action_override.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT submit or build the payload.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

_RDD_ALLOWED_ROLES: frozenset[str] = frozenset({"DD_ENGINEER"})


@trace_node("rdd_review_entry", "AGENT")
async def rdd_review_entry_node(state: ServiceRequestState) -> dict[str, Any]:
    """Parse RDD_REVIEW entry intent and validate role.

    Reads from state
    ----------------
    ``action_override``  — UI-initiated action.
    ``backend_refs``     — checked for ``user_role``.

    Writes to state
    ---------------
    ``backend_refs["rdd_action"]``  — ``"submit"`` when set via action_override.
    ``status``                      — ``"WAITING_FOR_USER"`` on role denial.
    ``response_message``            — set when short-circuiting.
    """
    action_override: str | None = state.get("action_override")
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    user_role: str | None = backend_refs.get("user_role")

    # ── 0. Role guard ──────────────────────────────────────────────────────
    if user_role and user_role.upper() not in _RDD_ALLOWED_ROLES:
        log.warning("rdd_review_entry.role_denied", user_role=user_role)
        return {
            "status": "WAITING_FOR_USER",
            "response_message": (
                "You do not have permission to perform RDD review actions. "
                "This stage requires the DD Engineer role."
            ),
        }

    # ── 1. Explicit UI actions ─────────────────────────────────────────────
    if action_override == "submit_rdd_report":
        log.info("rdd_review_entry.action_submit")
        backend_refs["rdd_action"] = "submit"
        return {"backend_refs": backend_refs}

    if action_override == "cancel_update":
        log.info("rdd_review_entry.action_cancel")
        return {
            "status": "WAITING_FOR_USER",
            "response_message": "Update cancelled. What would you like to do next?",
        }

    if action_override == "upload_document":
        log.info("rdd_review_entry.action_upload_document")
        return {
            "status": "WAITING_FOR_USER",
            "response_message": "Please use the upload interface to attach the RDD handover report.",
        }

    # ── 2. No action override — fall through to field_extraction ──────────
    return {}
