"""Boundary between free-form chat and the structured handover workflow.

Responsibilities
----------------
- Act as the first node in the handover data pipeline for every turn where
  ``active_agent`` is already set (the supervisor/registry have already run on
  a prior turn).
- Detect the user's confirmation response when ``confirmation_status == "PENDING"``:
    - Explicit YES phrases → set ``confirmation_status = "CONFIRMED"``
    - Explicit NO / change phrases → set ``confirmation_status = "REJECTED"``
    - Ambiguous input → leave confirmation_status unchanged (re-show card)
- Detect explicit cancel / workflow-switch phrases and clear ``active_agent``
  so the next routing step re-enters through the supervisor.

Non-responsibilities
--------------------
- MUST NOT collect or validate form fields.
- MUST NOT call the LLM.
- MUST NOT submit service requests.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phrase sets — kept intentionally broad so users don't have to type exactly
# ---------------------------------------------------------------------------

_CONFIRM_PHRASES: frozenset[str] = frozenset(
    {
        "yes",
        "yep",
        "yeah",
        "yup",
        "confirm",
        "confirmed",
        "submit",
        "proceed",
        "correct",
        "looks good",
        "that's correct",
        "thats correct",
        "go ahead",
        "approve",
        "ok",
        "okay",
        "sure",
        "absolutely",
        "agree",
    }
)

_REJECT_PHRASES: frozenset[str] = frozenset(
    {
        "no",
        "nope",
        "nah",
        "cancel",
        "change",
        "update",
        "edit",
        "modify",
        "wrong",
        "incorrect",
        "not right",
        "that's wrong",
        "thats wrong",
        "fix",
        "correct it",
        "i want to change",
        "let me change",
    }
)

_CANCEL_WORKFLOW_PHRASES: frozenset[str] = frozenset(
    {
        "start over",
        "restart",
        "new request",
        "different request",
        "begin again",
        "reset",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _contains_phrase(message: str, phrases: frozenset[str]) -> bool:
    """Return True if *message* contains any phrase as a whole word/phrase.

    Uses word-boundary matching so short words like "no" do not accidentally
    match inside longer words such as "not", "nothing", or "visible".
    Multi-word phrases (e.g. "let me change") are matched with surrounding
    word boundaries so they are not triggered by sub-phrase occurrences.
    """
    lowered = message.lower()
    return any(
        bool(re.search(r"\b" + re.escape(phrase) + r"\b", lowered))
        for phrase in phrases
    )


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@trace_node("handover_entry", "AGENT")
async def handover_entry_node(state: ServiceRequestState) -> dict[str, Any]:
    """Parse user intent at the boundary of the structured handover workflow.

    Reads from state
    ----------------
    ``confirmation_status``  — if PENDING, interpret the user's message as
                               a yes/no confirmation response.
    ``active_agent``         — if set and user wants to restart, clear it.
    ``user_message``         — the raw user input to parse.

    Writes to state
    ---------------
    ``confirmation_status``  — CONFIRMED or REJECTED when a clear signal is
                               detected; unchanged otherwise.
    ``active_agent``         — cleared (None) when the user wants to restart.
    """
    user_message: str = state.get("user_message") or ""
    confirmation_status: str | None = state.get("confirmation_status")
    action_override: str | None = state.get("action_override")  # type: ignore[assignment]

    # ── 0. Explicit UI action — takes priority over text parsing ───────────
    if action_override == "confirm":
        log.info("handover_entry.action_override_confirm")
        return {"confirmation_status": "CONFIRMED"}

    if action_override == "cancel":
        log.info("handover_entry.action_override_cancel")
        return {
            "confirmation_status": "REJECTED",
            "response_message": (
                "No problem — what would you like to change? "
                "Please tell me which field to update."
            ),
        }

    # ── 1. Workflow cancel / restart ───────────────────────────────────────
    if _contains_phrase(user_message, _CANCEL_WORKFLOW_PHRASES):
        log.info(
            "handover_entry.workflow_cancel",
            user_message=user_message[:120],
        )
        # Clear ALL workflow-specific state so the next turn starts with a
        # completely clean slate.  Without this, fields like collected_data,
        # selected_lease, and the stale confirmation card (response_ui) remain
        # in the persisted session and contaminate any subsequent request.
        return {
            # Routing / agent state
            "active_agent": None,
            "intent": None,
            "service_category": None,
            "sub_category": None,
            "workflow_stage": None,
            # Confirmation state
            "confirmation_status": None,
            "confirmation_required": False,
            # Collected / extracted data
            "collected_data": {},
            "extracted_fields": {},
            "missing_fields": [],
            "validation_errors": [],
            # Lease resolution
            "selected_lease": None,
            "lease_matches": [],
            # Stale UI (prevent old confirmation card from leaking into next response)
            "response_ui": {},
            # Turn control
            "status": "WAITING_FOR_USER",
            "response_message": (
                "Sure — I've cleared everything. What would you like to do next?"
            ),
        }

    # ── 2. Confirmation response parsing ──────────────────────────────────
    if confirmation_status == "PENDING":
        if _contains_phrase(user_message, _CONFIRM_PHRASES):
            log.info("handover_entry.confirmation_accepted")
            return {"confirmation_status": "CONFIRMED"}

        if _contains_phrase(user_message, _REJECT_PHRASES):
            log.info("handover_entry.confirmation_rejected")
            return {
                "confirmation_status": "REJECTED",
                "response_message": (
                    "No problem — what would you like to change? "
                    "Please tell me which field to update."
                ),
            }

        # Ambiguous — re-show the confirmation card on the next response_generation pass.
        log.info(
            "handover_entry.confirmation_ambiguous",
            user_message=user_message[:120],
        )
        return {
            "response_message": (
                "Please reply with 'yes' to confirm and submit, "
                "or tell me what you'd like to change."
            ),
        }

    return {}
