"""Submit validated, confirmed draft to the Service Request API.

Responsibilities
----------------
* Guard: proceed only when ``confirmation_status == "CONFIRMED"``.  Any other
  value (PENDING, REJECTED, None) causes an immediate FAILED exit.
* Guard: block if ``validation_errors`` contains any entry with
  ``blocking == True``.  This cannot be bypassed via user text or by the LLM.
* Guard: block if the built payload is absent from ``backend_refs``
  (``payload_builder_node`` must have run successfully first).
* Call ``ServiceRequestAPIService.create_service_request`` with the payload.
* Capture observability data:
    - Redacted payload snapshot before the API call.
    - TOOL/API call record including status code, latency, correlation ID,
      and error message.
* Write an audit log entry when the SR is created successfully.
* Update state: ``backend_refs.sr_id``, ``backend_refs.service_request_status``,
  ``status`` (SUBMITTED | FAILED), ``workflow_stage`` (SR_CREATED on success),
  and ``response_message``.

Non-responsibilities
--------------------
* Does not call the LLM — this is a deterministic execution node.
* Does not build the payload — that is ``payload_builder_node``.
* Does not process user confirmation — that is the supervisor / confirmation node.
* The LLM must never invoke this node directly; it is wired as a graph edge
  that fires only after explicit human confirmation.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agents.graph.state import ServiceRequestState
from app.agents.services.service_request_api_service import (
    AbstractServiceRequestAPIService,
    get_service_request_api_service,
)
from app.db.repositories.audit_log_repo import AuditLogRepository
from app.observability.decorators import trace_node
from app.observability.redaction import redact

logger = logging.getLogger(__name__)

_TOOL_NAME = "service_request_api.create_service_request"
_TOOL_TYPE = "API"

# ---------------------------------------------------------------------------
# Internal guards
# ---------------------------------------------------------------------------


def _has_blocking_errors(validation_errors: list[dict[str, Any]]) -> bool:
    """Return ``True`` if any validation error is marked as blocking.

    The ``blocking`` key defaults to ``True`` when absent so that unknown
    error shapes are treated conservatively.
    """
    return any(e.get("blocking", True) for e in validation_errors)


def _to_uuid(value: str | UUID | None) -> UUID | None:
    """Coerce *value* to ``UUID``; return ``None`` on failure."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


@trace_node("api_submission", "TOOL")
async def api_submission_node(state: ServiceRequestState) -> dict[str, Any]:
    """Submit the Service Request payload to the SR API.

    Reads from state
    ----------------
    ``confirmation_status``  — must be ``"CONFIRMED"``; aborts if not.
    ``validation_errors``    — aborts if any blocking error is present.
    ``backend_refs``         — must contain ``"create_payload"`` built by
                               ``payload_builder_node``.
    ``trace_manager``        — optional ``TraceManager`` for span / tool call
                               recording.
    ``trace_id``             — optional trace UUID; required for tracing.
    ``session_id``           — used for audit log writes.
    ``user_id``              — used for audit log writes.

    Writes to state
    ---------------
    ``backend_refs``         — enriched with ``sr_id``, ``service_request_status``,
                               and (when available) ``correlation_id``.
    ``status``               — ``"SUBMITTED"`` on success; ``"FAILED"`` otherwise.
    ``workflow_stage``       — ``"SR_CREATED"`` on success (unchanged on failure).
    ``response_message``     — human-readable outcome for the chat interface.
    """
    # ── 1. Confirmation guard ──────────────────────────────────────────────────
    confirmation_status: str | None = state.get("confirmation_status")
    if confirmation_status != "CONFIRMED":
        logger.warning(
            "api_submission_node: blocked — confirmation_status=%s (expected CONFIRMED)",
            confirmation_status,
        )
        return {
            "status": "FAILED",
            "response_message": (
                "Submission blocked: the service request has not been confirmed. "
                "Please review the details and confirm before submitting."
            ),
        }

    # ── 2. Blocking-validation guard ──────────────────────────────────────────
    validation_errors: list[dict[str, Any]] = state.get("validation_errors") or []
    if _has_blocking_errors(validation_errors):
        blocking_count = sum(1 for e in validation_errors if e.get("blocking", True))
        logger.warning(
            "api_submission_node: blocked — %d blocking validation error(s) present",
            blocking_count,
        )
        return {
            "status": "FAILED",
            "response_message": (
                f"Submission blocked: {blocking_count} validation error(s) must be "
                "resolved before this request can be submitted."
            ),
        }

    # ── 3. Payload guard ───────────────────────────────────────────────────────
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    payload: dict[str, Any] | None = backend_refs.get("create_payload")
    if not payload:
        logger.warning(
            "api_submission_node: blocked — create_payload missing from backend_refs"
        )
        return {
            "status": "FAILED",
            "response_message": (
                "Submission blocked: the request payload could not be found. "
                "Please try again or contact support."
            ),
        }

    # ── 4. Observability setup ─────────────────────────────────────────────────
    trace_manager = state.get("trace_manager")  # type: ignore[assignment]
    trace_id: UUID | None = _to_uuid(state.get("trace_id"))
    # Parent run_id injected by @trace_node so the API call span nests under
    # the api_submission node span in the run tree.
    node_run_id: UUID | None = _to_uuid(state.get("_trace_node_run_id"))
    run_id: UUID | None = None

    if trace_manager is not None and trace_id is not None:
        run_id = await trace_manager.start_run(
            trace_id=trace_id,
            run_name=_TOOL_NAME,
            run_type="TOOL",
            parent_run_id=node_run_id,
            input={"payload_keys": sorted(payload.keys())},
        )

    # Capture redacted payload snapshot before the API call.
    if trace_manager is not None and trace_id is not None and run_id is not None:
        redacted_payload = redact(payload)
        await trace_manager.capture_state_snapshot(
            trace_id=trace_id,
            run_id=run_id,
            snapshot_type="PAYLOAD_BUILDER_OUTPUT",
            state=redacted_payload,
        )

    # ── 5. API call ────────────────────────────────────────────────────────────
    svc: AbstractServiceRequestAPIService = get_service_request_api_service()
    result = await svc.create_service_request(payload)

    logger.info(
        "api_submission_node: status_code=%s sr_id=%s latency_ms=%s correlation_id=%s error=%s",
        result.status_code,
        result.sr_id,
        result.latency_ms,
        result.correlation_id,
        result.error,
    )

    # ── 6. Record the API call in the trace ────────────────────────────────────
    api_success = result.error is None and result.sr_id is not None

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
                "correlation_id": result.correlation_id,
                "status_code": result.status_code,
                "latency_ms": result.latency_ms,
                "error": result.error,
            },
            status="SUCCESS" if api_success else "FAILED",
            error_message=result.error,
        )

    # ── 7. Failure path ────────────────────────────────────────────────────────
    if not api_success:
        backend_refs["service_request_status"] = "FAILED"
        error_detail = f" (Detail: {result.error})" if result.error else ""
        return {
            "backend_refs": backend_refs,
            "status": "FAILED",
            "response_message": (
                "I was unable to submit your service request due to an API error. "
                f"Please try again later or contact support.{error_detail}"
            ),
        }

    # ── 8. Success — enrich backend_refs ──────────────────────────────────────
    backend_refs["sr_id"] = result.sr_id
    backend_refs["service_request_status"] = "SUBMITTED"
    if result.correlation_id:
        backend_refs["correlation_id"] = result.correlation_id

    # ── 9. Audit log ───────────────────────────────────────────────────────────
    session_id: UUID | None = _to_uuid(state.get("session_id"))
    user_id: UUID | None = _to_uuid(state.get("user_id"))

    if trace_manager is not None and session_id is not None:
        try:
            repo = AuditLogRepository(trace_manager._session)
            await repo.create(
                session_id=session_id,
                action="service_request.created",
                actor_user_id=user_id,
                after_state={
                    "sr_id": result.sr_id,
                    "correlation_id": result.correlation_id,
                    "status_code": result.status_code,
                    "latency_ms": result.latency_ms,
                },
                metadata={
                    "endpoint": result.endpoint,
                    "lease_code": payload.get("lease_code"),
                    "workflow_stage": "CREATE_SR",
                },
            )
            logger.info(
                "api_submission_node: audit log created for sr_id=%s session_id=%s",
                result.sr_id,
                session_id,
            )
        except Exception:
            # Audit log failures must never abort the submission.
            logger.warning(
                "api_submission_node: audit log write failed (non-fatal)",
                exc_info=True,
            )

    # ── 10. Return success state updates ──────────────────────────────────────
    return {
        "backend_refs": backend_refs,
        "status": "SUBMITTED",
        "workflow_stage": "SR_CREATED",
        "response_message": (
            f"Your Handover Service Request has been successfully submitted. "
            f"Your reference number is **{result.sr_id}**. "
            "You will be notified of any updates."
        ),
    }
