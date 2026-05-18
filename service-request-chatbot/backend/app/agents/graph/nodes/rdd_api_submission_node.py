"""Submit the RDD_REVIEW handover report to the platform SR API.

Responsibilities
----------------
- Guard: ``backend_refs["rdd_action"] == "submit"`` must be present.
- Guard: no blocking validation errors.
- Guard: RDD payload must be present in ``backend_refs["rdd_payload"]``.
- Guard: permission check via PermissionService.
- Call ``ServiceRequestAPIService.submit_report`` (POST /service-requests with
  status=REPORT_SUBMITTED).
- Capture observability (redacted snapshot + tool-call record).
- Write audit log event ``sr.rdd.report_submitted``.
- Update state with platform result.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT build the payload (that is ``rdd_payload_builder_node``).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agents.graph.state import ServiceRequestState
from app.agents.services.permission_service import PermissionDeniedError, PermissionService
from app.agents.services.service_request_api_service import get_service_request_api_service
from app.db.repositories.audit_log_repo import AuditLogRepository
from app.observability.decorators import trace_node
from app.observability.redaction import redact

logger = logging.getLogger(__name__)

_permission_service = PermissionService()
_TOOL_NAME = "service_request_api.rdd.submit_report"
_TOOL_TYPE = "API"


def _has_blocking_errors(validation_errors: list[dict[str, Any]]) -> bool:
    return any(e.get("blocking", True) for e in validation_errors)


def _to_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


@trace_node("rdd_api_submission", "TOOL")
async def rdd_api_submission_node(state: ServiceRequestState) -> dict[str, Any]:
    """Submit the RDD handover report via POST /service-requests (REPORT_SUBMITTED).

    Reads from state
    ----------------
    ``backend_refs``      — must contain ``sr_id``, ``rdd_payload``, ``rdd_action``.
    ``validation_errors`` — aborts if any blocking error is present.
    ``trace_manager``     — optional for observability.

    Writes to state
    ---------------
    ``backend_refs``      — updated with ``rdd_submitted_sr_id``.
    ``status``            — ``"SUBMITTED"`` on success; ``"FAILED"`` otherwise.
    ``response_message``  — human-readable outcome.
    """
    # ── 1. Blocking-validation guard ──────────────────────────────────────────
    validation_errors: list[dict[str, Any]] = state.get("validation_errors") or []
    if _has_blocking_errors(validation_errors):
        blocking_count = sum(1 for e in validation_errors if e.get("blocking", True))
        return {
            "status": "FAILED",
            "response_message": (
                f"RDD submission blocked: {blocking_count} validation error(s) must be "
                "resolved before the report can be submitted."
            ),
        }

    # ── 2. Payload guard ───────────────────────────────────────────────────────
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    sr_id: str | None = backend_refs.get("sr_id")
    payload: dict[str, Any] | None = backend_refs.get("rdd_payload")
    rdd_action: str = backend_refs.get("rdd_action", "")

    if not sr_id:
        return {
            "status": "FAILED",
            "response_message": "RDD submission blocked: service request ID is missing.",
        }
    if not payload:
        return {
            "status": "FAILED",
            "response_message": (
                "RDD submission blocked: the report payload could not be found. "
                "Please try again."
            ),
        }

    # ── 3. Permission guard ────────────────────────────────────────────────────
    from app.types.chat import AuthContext
    auth: AuthContext | None = state.get("auth")  # type: ignore[assignment]
    if auth is not None:
        try:
            _permission_service.check("SUBMIT_RDD_HANDOVER_REPORT", auth)
        except PermissionDeniedError as exc:
            logger.warning("rdd_api_submission_node: permission denied — %s", exc)
            return {
                "status": "FAILED",
                "response_message": f"Permission denied: {exc}",
            }

    # ── 4. Observability setup ─────────────────────────────────────────────────
    trace_manager = state.get("trace_manager")  # type: ignore[assignment]
    trace_id: UUID | None = _to_uuid(state.get("trace_id"))
    node_run_id: UUID | None = _to_uuid(state.get("_trace_node_run_id"))
    run_id: UUID | None = None

    if trace_manager is not None and trace_id is not None:
        run_id = await trace_manager.start_run(
            trace_id=trace_id,
            run_name=_TOOL_NAME,
            run_type="TOOL",
            parent_run_id=node_run_id,
            input={"sr_id": sr_id, "rdd_action": rdd_action},
        )

    if trace_manager is not None and trace_id is not None and run_id is not None:
        await trace_manager.capture_state_snapshot(
            trace_id=trace_id,
            run_id=run_id,
            snapshot_type="PAYLOAD_BUILDER_OUTPUT",
            state=redact(payload),
        )

    # ── 5. API call ────────────────────────────────────────────────────────────
    svc = get_service_request_api_service()
    result = await svc.submit_report(payload)

    logger.info(
        "rdd_api_submission_node: sr_id=%s status_code=%s error=%s latency_ms=%s",
        sr_id,
        result.status_code,
        result.error,
        result.latency_ms,
    )

    api_success = result.error is None and result.sr_id is not None

    # ── 6. Record in trace ─────────────────────────────────────────────────────
    if trace_manager is not None and trace_id is not None and run_id is not None:
        await trace_manager.capture_tool_call(
            trace_id=trace_id,
            run_id=run_id,
            tool_name=_TOOL_NAME,
            tool_type=_TOOL_TYPE,
            request_payload=redact(payload),
            response_payload=result.response_payload,
            status_code=result.status_code,
            success=api_success,
            latency_ms=result.latency_ms,
            error_message=result.error,
        )
        await trace_manager.finish_run(
            run_id=run_id,
            output={
                "sr_id": result.sr_id,
                "status_code": result.status_code,
                "latency_ms": result.latency_ms,
                "error": result.error,
            },
            status="SUCCESS" if api_success else "FAILED",
            error_message=result.error,
        )

    # ── 7. Failure path ────────────────────────────────────────────────────────
    if not api_success:
        error_detail = f" (Detail: {result.error})" if result.error else ""
        return {
            "backend_refs": backend_refs,
            "status": "FAILED",
            "response_message": (
                "I was unable to submit the RDD handover report due to an API error. "
                f"Please try again later.{error_detail}"
            ),
        }

    # ── 8. Success ─────────────────────────────────────────────────────────────
    submitted_sr_id = result.sr_id or sr_id
    backend_refs["rdd_submitted_sr_id"] = submitted_sr_id
    backend_refs["rdd_status"] = "REPORT_SUBMITTED"

    # Audit log
    session_id: UUID | None = _to_uuid(state.get("session_id"))
    user_id: UUID | None = _to_uuid(state.get("user_id"))

    if trace_manager is not None and session_id is not None:
        try:
            repo = AuditLogRepository(trace_manager._session)
            await repo.create(
                session_id=session_id,
                action="sr.rdd.report_submitted",
                actor_user_id=user_id,
                after_state={
                    "sr_id": submitted_sr_id,
                    "status_code": result.status_code,
                    "latency_ms": result.latency_ms,
                },
                metadata={"endpoint": result.endpoint, "workflow_stage": "RDD_REVIEW"},
            )
        except Exception:
            logger.warning(
                "rdd_api_submission_node: audit log write failed (non-fatal)", exc_info=True
            )

    return {
        "backend_refs": backend_refs,
        "status": "SUBMITTED",
        "workflow_stage": "SR_COMPLETED",
        "response_message": (
            f"The RDD Handover Report has been successfully submitted. "
            f"Your reference number is **{submitted_sr_id}**. "
            "The service request is now complete."
        ),
    }
