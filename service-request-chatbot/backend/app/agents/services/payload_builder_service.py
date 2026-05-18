"""Build the upstream API payload for Handover Service Request creation.

``build_create_handover_payload`` is the primary public function.  It maps
the validated ``collected_data`` dict to the exact shape expected by the
backend service for the initial (Mall Manager) CREATE_SR submission.

Design notes
------------
* Pure deterministic data mapping — no LLM calls, no I/O.
* ``status`` is intentionally absent from the payload; the backend
  auto-approves level 1 on creation.
* Required keys are validated before the payload dict is returned; any
  missing key raises ``ValueError`` with a descriptive message so callers
  can surface the error before attempting a network call.
* ``startDateLT`` and ``endDateLT`` are timezone-localised date variants
  optionally enriched by the lease-lookup flow; they default to ``""`` when
  absent so payload shape remains stable.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Required data keys ────────────────────────────────────────────────────────

# Every key in this set must be present (non-None, non-"", non-[]) in the
# ``data`` dict passed to ``build_create_handover_payload``.
# Optional fields such as "comments" and "notes" are intentionally excluded:
# they may be empty strings when the user declines to provide them, and the
# upstream API accepts an empty string for those fields.
_REQUIRED_DATA_KEYS: frozenset[str] = frozenset(
    {
        "mall",
        "brand",
        "lease_code",
        "title",
        "endDate",
        "startDate",
        "description",
        "inspection_done_by",
        "lease_brand_mall",
        "unit_codes",
        "contracted_area",
        "city",
        "brand_id",
        "tenant_profile_id",
        "contract_id",
        "property_id",
        "lease_id",
    }
)

# ── Internal helpers ───────────────────────────────────────────────────────────


def _validate_required_keys(data: dict[str, Any]) -> None:
    """Raise ``ValueError`` when any required key is absent or empty.

    Absence means: the key is missing from *data*, or its value is ``None``,
    ``""``, or ``[]``.  Integer ``0`` and boolean ``False`` are valid values.
    """
    missing: list[str] = [
        key
        for key in sorted(_REQUIRED_DATA_KEYS)
        if (lambda v: v is None or v == "" or v == [])(data.get(key))
    ]

    if missing:
        raise ValueError(
            f"build_create_handover_payload: missing required data keys: {missing}"
        )


# ── Public API ────────────────────────────────────────────────────────────────


def build_create_handover_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Build the CREATE_SR submission payload from validated ``collected_data``.

    Parameters
    ----------
    data:
        The validated ``collected_data`` dict from the graph state.  All keys
        listed in ``_REQUIRED_DATA_KEYS`` must be present and non-empty.

    Returns
    -------
    dict
        The complete payload ready for the Handover Service Request API.
        ``service_request_id`` is set to ``""`` for new requests (the backend
        assigns an ID on creation).

    Raises
    ------
    ValueError
        If any required key is absent or empty in *data*.
    """
    _validate_required_keys(data)

    payload: dict[str, Any] = {
        "payload": {
            "mall": data["mall"],
            "brand": data["brand"],
            "lease": data["lease_code"],
            "notes": data.get("notes", ""),
            "title": data["title"],
            "endDate": data["endDate"],
            "comments": data.get("comments", ""),
            "startDate": data["startDate"],
            "attachments": "",
            "description": data["description"],
            "documents_ids": [],
            "guideLineLink": "",
            "inspectionDoneBy": data["inspection_done_by"],
            "lease_brand_mall": data["lease_brand_mall"],
            "inspection_done_by": data["inspection_done_by"],
            "document_status_map": [],
            "unit_readiness_date": "",
            "expected_handover_date": "",
            "company_name": str(data["tenant_profile_id"]),
            "tenant_contact": "",
            "user_action": None,
            "unit_codes": data["unit_codes"],
            "contracted_area": data["contracted_area"],
            "city": data["city"],
            "brand_id": data["brand_id"],
            "tenant_profile_id": data["tenant_profile_id"],
            "contract_id": data["contract_id"],
            "property_id": data["property_id"],
            # Timezone-localised date variants; optional — default to "" when absent.
            "startDateLT": data.get("startDateLT", ""),
            "endDateLT": data.get("endDateLT", ""),
        },
        "title": data["title"],
        "tenant_profile_id": data["tenant_profile_id"],
        "property_id": data["property_id"],
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "lease_code": data["lease_code"],
        "lease_id": data["lease_id"],
        "service_request_id": "",
    }

    logger.debug(
        "build_create_handover_payload: payload built for lease_code=%s tenant_profile_id=%s",
        data["lease_code"],
        data["tenant_profile_id"],
    )

    return payload


# ── PayloadBuilderService class (DI / backward-compatible wrapper) ────────────


class PayloadBuilderService:
    """Thin class wrapper around the module-level payload builder functions.

    Use the module-level ``build_create_handover_payload`` directly where
    possible.  This class exists for dependency-injection patterns and
    backward compatibility with code that imports ``PayloadBuilderService``.
    """

    def build(self, draft: dict[str, object]) -> dict[str, object]:
        """Backward-compatible passthrough (does not validate or transform)."""
        return dict(draft)

    def build_create_handover_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        """Delegate to the module-level ``build_create_handover_payload``."""
        return build_create_handover_payload(data)
