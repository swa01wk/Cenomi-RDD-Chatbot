"""Submit FM_REVIEW PATCH to the platform SR API.

Responsibilities
----------------
- Guard: confirmation/action must be present (``backend_refs["fm_action"]``).
- Guard: no blocking validation errors.
- Guard: FM payload must be present in ``backend_refs["fm_payload"]``.
- Guard: permission check via PermissionService.
- Call ``ServiceRequestAPIService.patch_service_request`` with the payload.
- Capture observability (redacted payload snapshot, tool-call record).
- Write audit log event (``sr.fm.progress_saved`` or ``sr.fm.approved``).
- Update state with platform result.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT build the payload (that is ``fm_payload_builder_node``).
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

_TOOL_NAME_SAVE = "service_request_api.fm.patch_save_progress"
_TOOL_NAME_APPROVE = "service_request_api.fm.patch_approve"
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


@trace_node("fm_api_submission", "TOOL")
async def fm_api_submission_node(state: ServiceRequestState) -> dict[str, Any]:
    """PATCH the SR at the FM_REVIEW stage (save progress or approve).

    Reads from state
    ----------------
    ``backend_refs``      — must contain ``sr_id``, ``fm_payload``, ``fm_action``.
    ``validation_errors`` — aborts if any blocking error is present.
    ``trace_manager``     — optional for observability.

    Writes to state
    ---------------
    ``backend_refs``      — updated with ``fm_status``.
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
                f"FM submission blocked: {blocking_count} validation error(s) must be "
                "resolved before the FM review can be submitted."
            ),
        }

    # ── 2. Payload guard ───────────────────────────────────────────────────────
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    sr_id: str | None = backend_refs.get("sr_id")
    payload: dict[str, Any] | None = backend_refs.get("fm_payload")
    fm_action: str = backend_refs.get("fm_action", "save_progress")

    if not sr_id:
        return {
            "status": "FAILED",
            "response_message": "FM submission blocked: service request ID is missing.",
        }
    if not payload:
        return {
            "status": "FAILED",
            "response_message": (
                "FM submission blocked: the FM payload could not be found. "
                "Please try again."
            ),
        }

    # ── 3. Permission guard ────────────────────────────────────────────────────
    from app.types.chat import AuthContext
    auth: AuthContext | None = state.get("auth")  # type: ignore[assignment]
    if auth is not None:
        try:
            action_name = (
                "APPROVE_FM_HANDOVER"
                if fm_action == "approve"
                else "SAVE_FM_HANDOVER_PROGRESS"
            )
            _permission_service.check(action_name, auth)
        except PermissionDeniedError as exc:
            logger.warning("fm_api_submission_node: permission denied — %s", exc)
            return {
                "status": "FAILED",
                "response_message": f"Permission denied: {exc}",
            }

    # ── 4. Observability setup ─────────────────────────────────────────────────
    trace_manager = state.get("trace_manager")  # type: ignore[assignment]
    trace_id: UUID | None = _to_uuid(state.get("trace_id"))
    node_run_id: UUID | None = _to_uuid(state.get("_trace_node_run_id"))
    tool_name = _TOOL_NAME_APPROVE if fm_action == "approve" else _TOOL_NAME_SAVE
    run_id: UUID | None = None

    if trace_manager is not None and trace_id is not None:
        run_id = await trace_manager.start_run(
            trace_id=trace_id,
            run_name=tool_name,
            run_type="TOOL",
            parent_run_id=node_run_id,
            input={"sr_id": sr_id, "fm_action": fm_action},
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
    result = await svc.patch_service_request(sr_id, payload)

    logger.info(
        "fm_api_submission_node: sr_id=%s fm_action=%s status_code=%s error=%s latency_ms=%s",
        sr_id,
        fm_action,
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
            tool_name=tool_name,
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
                "I was unable to submit the FM review due to an API error. "
                f"Please try again later.{error_detail}"
            ),
        }

    # ── 8. Success ─────────────────────────────────────────────────────────────
    backend_refs["fm_status"] = "APPROVED" if fm_action == "approve" else "IN_PROCESS"

    # Audit log
    session_id: UUID | None = _to_uuid(state.get("session_id"))
    user_id: UUID | None = _to_uuid(state.get("user_id"))
    audit_action = "sr.fm.approved" if fm_action == "approve" else "sr.fm.progress_saved"

    if trace_manager is not None and session_id is not None:
        try:
            repo = AuditLogRepository(trace_manager._session)
            await repo.create(
                session_id=session_id,
                action=audit_action,
                actor_user_id=user_id,
                after_state={
                    "sr_id": result.sr_id,
                    "fm_action": fm_action,
                    "status_code": result.status_code,
                    "latency_ms": result.latency_ms,
                },
                metadata={"endpoint": result.endpoint, "workflow_stage": "FM_REVIEW"},
            )
        except Exception:
            logger.warning("fm_api_submission_node: audit log write failed (non-fatal)", exc_info=True)

    fm_message = (
        f"Your Handover Service Request has been approved at the FM review stage. "
        f"Reference: **{sr_id}**."
        if fm_action == "approve"
        else f"FM review progress has been saved for Service Request **{sr_id}**. "
        "The request remains in progress."
    )

    return {
        "backend_refs": backend_refs,
        "status": "SUBMITTED",
        "response_message": fm_message,
    }
