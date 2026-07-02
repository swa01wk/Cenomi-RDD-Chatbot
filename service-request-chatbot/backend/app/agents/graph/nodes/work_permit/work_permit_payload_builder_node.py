"""Build API payload for Work Permit SR creation."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)

_REQUIRED_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"lease_code", "lease_id", "work_permit_type", "start_date", "end_date"}
)


def build_create_work_permit_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Build the CREATE work permit API payload from validated collected_data.

    Raises ``ValueError`` when required keys are absent.
    """
    missing = [k for k in _REQUIRED_PAYLOAD_KEYS if not data.get(k)]
    if missing:
        raise ValueError(f"Work permit payload missing required keys: {missing}")

    return {
        "leaseId": data.get("lease_id"),
        "leaseCode": data.get("lease_code"),
        "propertyId": data.get("property_id"),
        "unitCodes": data.get("unit_codes") or [],
        "mall": data.get("mall", ""),
        "brand": data.get("brand", ""),
        "workPermitType": data.get("work_permit_type"),
        "description": data.get("description", ""),
        "startDate": data.get("start_date"),
        "endDate": data.get("end_date"),
        "contractorName": data.get("contractor_name", ""),
        "comments": data.get("comments", ""),
        "serviceCategory": "WORK_PERMIT",
        "subCategory": "WORK_PERMIT",
    }


@trace_node("work_permit_payload_builder", "TOOL")
async def work_permit_payload_builder_node(state: ServiceRequestState) -> dict[str, Any]:
    """Build the work permit payload and store it in backend_refs."""
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    workflow_stage: str = state.get("workflow_stage") or ""

    if workflow_stage != "CREATE_WORK_PERMIT":
        logger.info(
            "work_permit_payload_builder_node: skipped for stage=%s", workflow_stage
        )
        return {}

    try:
        payload = build_create_work_permit_payload(collected_data)
    except ValueError as exc:
        logger.warning("work_permit_payload_builder_node: %s", exc)
        return {"status": "FAILED"}

    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    backend_refs["create_payload"] = payload

    logger.info(
        "work_permit_payload_builder_node: payload built for lease_code=%s permit_type=%s",
        collected_data.get("lease_code"),
        collected_data.get("work_permit_type"),
    )
    return {"backend_refs": backend_refs}
