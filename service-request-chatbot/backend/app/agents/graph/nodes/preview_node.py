"""Preview node — fetch and summarise the current service request state.

Responsibilities
----------------
- If the session has a submitted SR (``backend_refs["sr_id"]`` is set), call the
  platform API to retrieve the live SR data and format it as a structured summary.
- If no SR has been submitted yet, format the draft ``collected_data`` from state.
- Emit ``response_ui`` with ``type = "sr_preview_card"`` so the frontend renders
  a dedicated read-only card with field rows and (when submitted) a status badge.
- Also set ``response_message`` as a text hint for the LLM in response_generation.

Non-responsibilities
--------------------
- MUST NOT modify ``collected_data``, routing fields, or any domain fields.
- MUST NOT submit or approve service requests.
- MUST NOT call the LLM.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.prompts.response_generation_prompt import FIELD_LABELS
from app.agents.services.service_request_api_service import get_service_request_api_service
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

# Fields shown in the preview card — ordered for readability.
_PREVIEW_FIELD_ORDER: list[tuple[str, str]] = [
    ("lease_code",             "Lease Code"),
    ("brand",                  "Brand"),
    ("mall",                   "Mall"),
    ("city",                   "City"),
    ("unit_codes",             "Units"),
    ("contracted_area",        "Contracted Area"),
    ("description",            "Description"),
    ("startDate",              "Inspection Start Date"),
    ("endDate",                "Inspection End Date"),
    ("inspection_done_by",     "Inspection Done By"),
    ("unit_readiness_date",    "Unit Readiness Date"),
    ("expected_handover_date", "Expected Handover Date"),
    ("actual_handover_date",   "Actual Handover Date"),
    ("fitout_start_date",      "Fitout Start Date"),
    ("fitout_end_date",        "Fitout End Date"),
    ("trading_date",           "Trading Date"),
    ("comments",               "Comments"),
    ("guideLineLink",          "Guideline Link"),
]

# Same keys from the platform API payload blob.
_PLATFORM_FIELD_ORDER: list[tuple[str, str]] = [
    ("title",                  "Title"),
    ("description",            "Description"),
    ("startDate",              "Inspection Start Date"),
    ("endDate",                "Inspection End Date"),
    ("inspection_done_by",     "Inspection Done By"),
    ("unit_readiness_date",    "Unit Readiness Date"),
    ("expected_handover_date", "Expected Handover Date"),
    ("actual_handover_date",   "Actual Handover Date"),
    ("fitout_start_date",      "Fitout Start Date"),
    ("fitout_end_date",        "Fitout End Date"),
    ("trading_date",           "Trading Date"),
    ("comments",               "Comments"),
    ("guideLineLink",          "Guideline Link"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(key: str, label: str, value: Any) -> dict[str, Any]:
    """Build a single preview field dict."""
    if isinstance(value, list):
        display = ", ".join(str(v) for v in value) if value else None
    elif value is None or value == "":
        display = None
    else:
        display = str(value)
    return {"key": key, "label": label, "value": display}


def _fields_from_collected(collected_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ordered field rows from draft collected_data.

    Only fields explicitly listed in ``_PREVIEW_FIELD_ORDER`` are included.
    Internal/system fields such as ``title``, ``brand_id``, ``lease_id``,
    ``contract_id``, ``property_id``, ``tenant_profile_id``, etc. that live in
    ``collected_data`` but are not meaningful to the user are intentionally
    excluded.
    """
    rows: list[dict[str, Any]] = []
    for key, label in _PREVIEW_FIELD_ORDER:
        val = collected_data.get(key)
        if val is not None and val != "" and val != []:
            rows.append(_field(key, label, val))
    return rows


def _fields_from_platform(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ordered field rows from a platform SR payload blob."""
    rows: list[dict[str, Any]] = []
    for key, label in _PLATFORM_FIELD_ORDER:
        val = payload.get(key)
        if val is not None and val != "":
            rows.append(_field(key, label, val))
    return rows


def _ops_field(ops: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarise workflow operations as a single display field."""
    if not ops:
        return None
    lines = []
    for op in ops:
        role = op.get("assigned_role") or op.get("role", "Unknown")
        status = op.get("status", "—")
        lines.append(f"{role}: {status}")
    return {"key": "workflow_operations", "label": "Workflow Stages", "value": " | ".join(lines)}


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@trace_node("preview", "LANGGRAPH_NODE")
async def preview_node(state: ServiceRequestState) -> dict[str, Any]:
    """Build a rich preview of the current service request for the user.

    Reads
    -----
    state["backend_refs"]   — checked for ``sr_id`` (platform-assigned ID).
    state["collected_data"] — used when no SR has been submitted.

    Writes
    ------
    state["response_ui"]      — ``sr_preview_card`` payload for the frontend.
    state["response_message"] — text hint for response_generation LLM polish.
    state["status"]           — set to ``"WAITING_FOR_USER"``.
    """
    backend_refs: dict[str, Any] = state.get("backend_refs") or {}
    sr_id: str | None = backend_refs.get("sr_id")
    collected_data: dict[str, Any] = state.get("collected_data") or {}

    if sr_id:
        # ── Submitted SR — fetch live data from the platform ──────────────
        log.info("preview_node.fetching_sr", sr_id=sr_id)
        try:
            api_service = get_service_request_api_service()
            result = await api_service.get_service_request(sr_id)
            if result.success:
                payload: dict[str, Any] = result.payload or {}
                fields = _fields_from_platform(payload)
                ops_row = _ops_field(result.service_request_operations or [])
                if ops_row:
                    fields.append(ops_row)

                response_ui: dict[str, Any] = {
                    "type": "sr_preview_card",
                    "message": f"Here is your submitted service request (ID: {sr_id}).",
                    "requestType": "Handover Service Request",
                    "srId": sr_id,
                    "status": result.status or "SUBMITTED",
                    "isSubmitted": True,
                    "fields": fields,
                }
                response_message = (
                    f"Show the user the service request (ID: {sr_id}) "
                    f"with status '{result.status}'. "
                    "The structured card is being shown; give a very short 1-sentence intro."
                )
                log.info("preview_node.sr_fetched", sr_id=sr_id, status=result.status)
            else:
                log.warning("preview_node.sr_fetch_failed", sr_id=sr_id, error=result.error)
                fields = _fields_from_collected(collected_data)
                response_ui = {
                    "type": "sr_preview_card",
                    "message": f"Could not fetch live SR {sr_id} — showing draft data.",
                    "requestType": "Handover Service Request",
                    "srId": sr_id,
                    "status": None,
                    "isSubmitted": False,
                    "fields": fields,
                }
                response_message = (
                    f"There was an issue fetching SR {sr_id} ({result.error}). "
                    "Showing collected draft data instead. Keep the intro very short."
                )
        except Exception as exc:
            log.exception("preview_node.sr_fetch_error", sr_id=sr_id, error=str(exc))
            fields = _fields_from_collected(collected_data)
            response_ui = {
                "type": "sr_preview_card",
                "message": f"Could not reach the platform for SR {sr_id} — showing draft data.",
                "requestType": "Handover Service Request",
                "srId": sr_id,
                "status": None,
                "isSubmitted": False,
                "fields": fields,
            }
            response_message = (
                "Platform unavailable. Showing draft data. Keep the intro very short."
            )
    else:
        # ── Not yet submitted — show collected draft data ─────────────────
        log.info("preview_node.showing_draft")
        fields = _fields_from_collected(collected_data)
        if not fields:
            response_ui = {
                "type": "sr_preview_card",
                "message": "Nothing has been collected yet in this session.",
                "requestType": "Handover Service Request",
                "srId": None,
                "status": None,
                "isSubmitted": False,
                "fields": [],
            }
            response_message = (
                "Nothing collected yet. Offer to help create, update, or check a service request."
            )
        else:
            response_ui = {
                "type": "sr_preview_card",
                "message": "Here is what has been collected so far (not yet submitted).",
                "requestType": "Handover Service Request",
                "srId": None,
                "status": "DRAFT",
                "isSubmitted": False,
                "fields": fields,
            }
            response_message = (
                "Here is the current draft. "
                "Give a very short 1-sentence intro; the structured card is being shown."
            )

    return {
        "response_ui": response_ui,
        "response_message": response_message,
        "status": "WAITING_FOR_USER",
    }
