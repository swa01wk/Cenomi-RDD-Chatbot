"""Entry node for the Work Permit SR workflow.

Responsibilities
----------------
- Parse confirmation responses (yes/no) when confirmation_status is PENDING.
- Handle explicit UI action overrides (confirm, cancel).
- Detect cancel/restart phrases and clear workflow state.

Non-responsibilities
--------------------
- Does not collect or validate form fields.
- Does not call the LLM.
- Does not submit service requests.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

_CONFIRM_PHRASES: frozenset[str] = frozenset(
    {
        "yes", "yep", "yeah", "yup", "confirm", "confirmed", "submit",
        "proceed", "correct", "looks good", "go ahead", "ok", "okay",
        "sure", "absolutely", "agree",
    }
)

_REJECT_PHRASES: frozenset[str] = frozenset(
    {
        "no", "nope", "nah", "cancel", "change", "update", "edit",
        "modify", "wrong", "incorrect", "fix",
    }
)

_CANCEL_WORKFLOW_PHRASES: frozenset[str] = frozenset(
    {"start over", "restart", "new request", "different request", "begin again", "reset"}
)


def _contains_phrase(message: str, phrases: frozenset[str]) -> bool:
    lowered = message.lower()
    return any(bool(re.search(r"\b" + re.escape(p) + r"\b", lowered)) for p in phrases)


@trace_node("work_permit_entry", "AGENT")
async def work_permit_entry_node(state: ServiceRequestState) -> dict[str, Any]:
    """Parse confirmation / cancel at the work permit workflow boundary."""
    user_message: str = state.get("user_message") or ""
    confirmation_status: str | None = state.get("confirmation_status")
    action_override: str | None = state.get("action_override")  # type: ignore[assignment]

    # ── 0. Explicit UI action ──────────────────────────────────────────────
    if action_override in ("confirm", "confirm_create_wp"):
        log.info("work_permit_entry.action_override_confirm")
        return {"confirmation_status": "CONFIRMED"}

    if action_override in ("cancel", "cancel_create_wp"):
        log.info("work_permit_entry.action_override_cancel")
        return {
            "confirmation_status": "REJECTED",
            "response_message": "No problem — what would you like to change?",
        }

    # ── 1. Workflow cancel / restart ───────────────────────────────────────
    if _contains_phrase(user_message, _CANCEL_WORKFLOW_PHRASES):
        log.info("work_permit_entry.workflow_cancel")
        return {
            "active_agent": None,
            "intent": None,
            "service_category": None,
            "sub_category": None,
            "workflow_stage": None,
            "confirmation_status": None,
            "confirmation_required": False,
            "collected_data": {},
            "extracted_fields": {},
            "missing_fields": [],
            "validation_errors": [],
            "selected_lease": None,
            "lease_matches": [],
            "response_ui": {},
            "status": "WAITING_FOR_USER",
            "response_message": "Sure — I've cleared everything. What would you like to do next?",
        }

    # ── 2. Confirmation response parsing ──────────────────────────────────
    if confirmation_status == "PENDING":
        if _contains_phrase(user_message, _CONFIRM_PHRASES):
            log.info("work_permit_entry.confirmation_accepted")
            return {"confirmation_status": "CONFIRMED"}

        if _contains_phrase(user_message, _REJECT_PHRASES):
            log.info("work_permit_entry.confirmation_rejected")
            return {
                "confirmation_status": "REJECTED",
                "response_message": "No problem — what would you like to change?",
            }

        return {
            "response_message": (
                "Please reply with 'yes' to confirm and submit, "
                "or tell me what you'd like to change."
            ),
        }

    # First turn for this agent — initialize workflow stage.
    if not state.get("workflow_stage"):
        return {"workflow_stage": "CREATE_WORK_PERMIT"}

    return {}
