"""Missing field detection utilities for the handover workflow.

Provides:
- ``get_missing_fields``: standalone function for detecting absent/empty fields.
- ``HANDOVER_FIELD_QUESTIONS``: mapping of field names to user-facing questions.
- ``MissingFieldService``: thin class kept for backward compatibility.
"""

from __future__ import annotations

from app.types.service_request import ValidationIssueDTO

# ---------------------------------------------------------------------------
# User-facing questions map
# ---------------------------------------------------------------------------

HANDOVER_FIELD_QUESTIONS: dict[str, str] = {
    "lease_code": "Ask the user for the lease code for this handover request.",
    "lease_brand_mall": "Ask the user for the lease, brand name, or mall name.",
    # "title" is intentionally omitted: it is auto-generated as
    # "handover-{lease_code}-{description_slug}" and never asked from the user.
    "description": "Ask the user for a short description of this handover request.",
    "startDate": "Ask the user when the inspection should start (date).",
    "endDate": "Ask the user when the inspection should end (date).",
    "inspection_done_by": "Ask the user who will perform the inspection. They must choose one of exactly two options: FM Manager or Operations. Make the two choices explicit.",
    "comments": "Ask the user if they have any additional comments for this request.",
    "unit_readiness_date": "Ask the user for the unit readiness date.",
    "expected_handover_date": "Ask the user for the expected handover date.",
    "guideLineLink": "Ask the user to provide the guideline link for the handover report.",
    "actual_handover_date": "Ask the user for the actual handover date.",
    "fitout_start_date": "Ask the user for the fitout start date.",
    "fitout_end_date": "Ask the user for the fitout end date.",
    "trading_date": "Ask the user for the trading date.",
}

# ---------------------------------------------------------------------------
# Standalone helper
# ---------------------------------------------------------------------------


def get_missing_fields(data: dict, required_fields: list[str]) -> list[str]:
    """Return entries from *required_fields* that are absent or empty in *data*.

    A field is considered missing when any of the following hold:
    - The key does not exist in *data*
    - The value is ``None``
    - The value is an empty string (``""``) — **unless** it is in
      ``OPTIONAL_FIELDS``, where any value other than ``None`` is accepted
      (the user explicitly declined to provide it).
    - The value is an empty list (``[]``)

    Mirrors the logic in ``handover_schema.get_missing_fields`` so both
    callers produce a consistent missing-field list.
    """
    from app.agents.schemas.handover_schema import OPTIONAL_FIELDS  # local import avoids circular

    missing: list[str] = []
    for field in required_fields:
        if field not in data:
            missing.append(field)
            continue
        value = data[field]
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and value == "" and field not in OPTIONAL_FIELDS:
            missing.append(field)
        elif isinstance(value, list) and len(value) == 0:
            missing.append(field)
    return missing


# ---------------------------------------------------------------------------
# Backward-compatible class
# ---------------------------------------------------------------------------


class MissingFieldService:
    def next_prompt(self, issues: list[ValidationIssueDTO]) -> str | None:
        if not issues:
            return None
        return "Ask the user to provide the missing information highlighted in the validation errors."
