"""Human confirmation before work permit SR submission.

Responsibilities
----------------
- Check all CREATE_WORK_PERMIT required fields are present.
- Build a confirmation card for the user to review.
- Transition to READY_TO_SUBMIT / PENDING state.

Non-responsibilities
--------------------
- Does not call the LLM.
- Does not submit or build the API payload.
- Does not process yes/no responses (that is work_permit_entry_node).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.schemas.work_permit_schema import (
    WORK_PERMIT_TYPE_LABELS,
    get_missing_fields,
)
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)

_FIELD_LABELS: dict[str, str] = {
    "lease_code": "Lease Code",
    "mall": "Mall",
    "brand": "Brand",
    "unit_codes": "Unit Codes",
    "work_permit_type": "Work Permit Type",
    "description": "Description of Work",
    "start_date": "Start Date",
    "end_date": "End Date",
    "contractor_name": "Contractor Name",
    "comments": "Comments",
}

_EDITABLE_FIELDS: frozenset[str] = frozenset(
    {"work_permit_type", "description", "start_date", "end_date", "contractor_name", "comments"}
)

_DISPLAY_FIELDS: tuple[str, ...] = (
    "lease_code", "mall", "brand", "unit_codes",
    "work_permit_type", "description", "start_date", "end_date",
    "contractor_name", "comments",
)

_CONFIRMATION_MESSAGE = (
    "All required details have been collected. Please review the Work Permit Service "
    "Request below and confirm, or let me know if you want to change anything."
)


def _build_confirmation_card(collected_data: dict[str, Any]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    for key in _DISPLAY_FIELDS:
        raw_val = collected_data.get(key)
        # Display human-readable label for work_permit_type
        if key == "work_permit_type" and raw_val:
            display_val = WORK_PERMIT_TYPE_LABELS.get(raw_val, raw_val)
        else:
            display_val = raw_val
        fields.append(
            {
                "key": key,
                "label": _FIELD_LABELS.get(key, key),
                "value": display_val,
                "editable": key in _EDITABLE_FIELDS,
            }
        )
    return {
        "type": "confirmation_card",
        "requestType": "Work Permit Service Request",
        "fields": fields,
        "message": _CONFIRMATION_MESSAGE,
    }


@trace_node("work_permit_confirmation", "AGENT")
async def work_permit_confirmation_node(state: ServiceRequestState) -> dict[str, Any]:
    """Generate confirmation card when all CREATE_WORK_PERMIT fields are present."""
    existing_status: str | None = state.get("confirmation_status")
    if existing_status == "CONFIRMED":
        return {}
    if existing_status == "REJECTED":
        extracted = state.get("extracted_fields") or {}
        corrected = state.get("corrected_fields") or {}
        if not extracted and not corrected:
            return {}

    collected_data: dict[str, Any] = state.get("collected_data") or {}
    missing = get_missing_fields("CREATE_WORK_PERMIT", collected_data)

    if missing:
        logger.info(
            "work_permit_confirmation_node: skipped — %d field(s) still missing: %s",
            len(missing), missing,
        )
        return {}

    logger.info("work_permit_confirmation_node: all fields present — generating confirmation card")

    return {
        "confirmation_required": True,
        "confirmation_status": "PENDING",
        "status": "READY_TO_SUBMIT",
        "response_ui": _build_confirmation_card(collected_data),
        "response_message": None,
    }
