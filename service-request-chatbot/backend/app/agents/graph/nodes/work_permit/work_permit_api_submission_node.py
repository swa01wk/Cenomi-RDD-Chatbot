"""Submit a confirmed Work Permit SR to the Service Request API.

Guards (same pattern as api_submission_node):
- confirmation_status must be CONFIRMED
- No blocking validation errors
- Payload must be present in backend_refs
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agents.graph.state import ServiceRequestState
from app.agents.services.service_request_api_service import get_service_request_api_service
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)


def _to_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


@trace_node("work_permit_api_submission", "TOOL")
async def work_permit_api_submission_node(state: ServiceRequestState) -> dict[str, Any]:
    """Submit the Work Permit SR payload to the SR API."""

    # ── 1. Confirmation guard ──────────────────────────────────────────────
    if state.get("confirmation_status") != "CONFIRMED":
        logger.warning("work_permit_api_submission_node: blocked — not confirmed")
        return {
            "status": "FAILED",
            "response_message": (
                "Submission blocked: the work permit request has not been confirmed. "
                "Please review the details and confirm before submitting."
            ),
        }

    # ── 2. Blocking validation guard ──────────────────────────────────────
    validation_errors: list[dict[str, Any]] = state.get("validation_errors") or []
    blocking = [e for e in validation_errors if e.get("blocking", True)]
    if blocking:
        logger.warning(
            "work_permit_api_submission_node: blocked — %d blocking error(s)", len(blocking)
        )
        return {
            "status": "FAILED",
            "response_message": (
                f"Submission blocked: {len(blocking)} validation error(s) must be "
                "resolved before this request can be submitted."
            ),
        }

    # ── 3. Payload guard ───────────────────────────────────────────────────
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    payload: dict[str, Any] | None = backend_refs.get("create_payload")
    if not payload:
        logger.warning("work_permit_api_submission_node: blocked — no create_payload")
        return {
            "status": "FAILED",
            "response_message": "Submission blocked: payload not found. Please try again.",
        }

    # ── 4. API call ────────────────────────────────────────────────────────
    svc = get_service_request_api_service()
    result = await svc.create_service_request(payload)

    logger.info(
        "work_permit_api_submission_node: status_code=%s sr_id=%s error=%s",
        result.status_code, result.sr_id, result.error,
    )

    if result.error or not result.sr_id:
        backend_refs["service_request_status"] = "FAILED"
        return {
            "backend_refs": backend_refs,
            "status": "FAILED",
            "response_message": (
                "Unable to submit the work permit request due to an API error. "
                f"Please try again later.{' Detail: ' + result.error if result.error else ''}"
            ),
        }

    backend_refs["sr_id"] = result.sr_id
    backend_refs["service_request_status"] = "SUBMITTED"
    if result.correlation_id:
        backend_refs["correlation_id"] = result.correlation_id

    return {
        "backend_refs": backend_refs,
        "status": "SUBMITTED",
        "workflow_stage": "WP_CREATED",
        "response_message": (
            f"Your Work Permit Service Request has been successfully submitted. "
            f"Your reference number is **{result.sr_id}**. "
            "You will be notified of any updates."
        ),
    }
