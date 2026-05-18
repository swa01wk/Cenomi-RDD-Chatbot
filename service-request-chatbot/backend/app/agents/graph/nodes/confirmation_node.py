"""Human confirmation before submission.

Responsibilities
----------------
* Check that all CREATE_SR required fields are present in ``collected_data``.
* If complete: build a deterministic confirmation card and transition the graph
  into the READY_TO_SUBMIT / PENDING confirmation state.
* If incomplete: return empty so the missing-field node can handle collection.

Non-responsibilities
--------------------
* Does not call the LLM.
* Does not submit or build the API payload.
* Does not modify ``collected_data``.
* Does not process the user's yes/no response (that is the supervisor's job).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.schemas.handover_schema import get_missing_fields
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)

# ── Display configuration ──────────────────────────────────────────────────────

# Human-readable labels for each field on the confirmation card.
_FIELD_LABELS: dict[str, str] = {
    "lease_code": "Lease Code",
    "brand": "Brand",
    "mall": "Mall",
    "unit_codes": "Unit Codes",
    "city": "City",
    "contracted_area": "Contracted Area (sqm)",
    "title": "Title",
    "description": "Description",
    "startDate": "Start Date",
    "endDate": "End Date",
    "inspection_done_by": "Inspection Done By",
    "comments": "Comments",
}

# Fields the user may inline-edit directly on the confirmation card.
# Read-only fields (lease info, backend IDs) are intentionally excluded.
_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "startDate",
        "endDate",
        "inspection_done_by",
        "comments",
    }
)

# Ordered list of fields rendered on the card (subset of required fields;
# backend-only IDs such as tenant_profile_id are intentionally excluded).
_CONFIRMATION_DISPLAY_FIELDS: tuple[str, ...] = (
    "lease_code",
    "brand",
    "mall",
    "unit_codes",
    "city",
    "contracted_area",
    "title",
    "description",
    "startDate",
    "endDate",
    "inspection_done_by",
    "comments",
)

_CONFIRMATION_MESSAGE = (
    "All required details have been collected. Present the confirmation card "
    "and invite the user to review and confirm the Handover Service Request, "
    "or let you know if they want to change anything."
)

# ── Internal helpers ───────────────────────────────────────────────────────────


def _build_confirmation_card(collected_data: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic confirmation card from *collected_data*.

    The card is purely derived from the input — identical inputs always
    produce an identical card, making it safe to regenerate on retry.

    Returns
    -------
    dict
        ``response_ui`` payload with ``type = "confirmation_card"``.
    """
    fields: list[dict[str, Any]] = [
        {
            "key": field_key,
            "label": _FIELD_LABELS.get(field_key, field_key),
            "value": collected_data.get(field_key),
            "editable": field_key in _EDITABLE_FIELDS,
        }
        for field_key in _CONFIRMATION_DISPLAY_FIELDS
    ]

    return {
        "type": "confirmation_card",
        "requestType": "Handover Service Request",
        "fields": fields,
        "message": _CONFIRMATION_MESSAGE,
    }


# ── Node ───────────────────────────────────────────────────────────────────────


@trace_node("confirmation", "AGENT")
async def confirmation_node(state: ServiceRequestState) -> dict[str, Any]:
    """Generate a confirmation card when all CREATE_SR required fields are present.

    The node is a no-op (returns ``{}``) in three situations:
    - Required fields are still missing (missing_field_node handles collection).
    - ``confirmation_status`` is already ``"CONFIRMED"`` — the user has already
      confirmed on this turn (set by ``handover_entry_node``); overwriting with
      ``"PENDING"`` would undo the confirmation and block submission.
    - ``confirmation_status`` is ``"REJECTED"`` — the user declined; the graph
      will route to response_generation to ask what to change.

    Reads from state
    ----------------
    ``collected_data``       — draft field values to confirm.
    ``workflow_stage``       — determines which required fields apply
                               (defaults to ``"CREATE_SR"``).
    ``confirmation_status``  — existing status; CONFIRMED/REJECTED are preserved.

    Writes to state
    ---------------
    ``confirmation_required``  — ``True`` when all required fields are present.
    ``confirmation_status``    — ``"PENDING"`` (awaiting explicit user response).
    ``status``                 — ``"READY_TO_SUBMIT"``.
    ``response_ui``            — confirmation card dict for the frontend.
    """
    existing_status: str | None = state.get("confirmation_status")
    if existing_status == "CONFIRMED":
        # Submission already authorised this turn — do not reset to PENDING.
        return {}
    if existing_status == "REJECTED":
        # Only rebuild the card when the user actually provided corrections
        # (i.e. field_extraction or corrected_fields produced new data).
        # If neither is present this is a pure cancel/reject turn — let
        # response_generation use the rejection message from handover_entry_node
        # and ask what to change.
        extracted = state.get("extracted_fields") or {}
        corrected = state.get("corrected_fields") or {}
        if not extracted and not corrected:
            return {}
    # REJECTED with corrections: field_extraction + merge_state have applied the
    # update; fall through to rebuild a fresh confirmation card so the user can
    # review the corrected data.  Clear the rejection status so the card is
    # rendered (not suppressed) by response_generation_node.

    collected_data: dict[str, Any] = state.get("collected_data") or {}
    workflow_stage: str = state.get("workflow_stage") or "CREATE_SR"

    missing = get_missing_fields(workflow_stage, collected_data)

    if missing:
        logger.info(
            "confirmation_node: skipped — %d required field(s) still missing for stage=%s: %s",
            len(missing),
            workflow_stage,
            missing,
        )
        return {}

    logger.info(
        "confirmation_node: all required fields present for stage=%s — generating confirmation card",
        workflow_stage,
    )

    confirmation_card = _build_confirmation_card(collected_data)

    return {
        "confirmation_required": True,
        "confirmation_status": "PENDING",
        "status": "READY_TO_SUBMIT",
        "response_ui": confirmation_card,
        # Clear any rejection message that handover_entry_node may have written;
        # the confirmation card is the authoritative response for this turn.
        "response_message": None,
    }
