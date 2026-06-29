"""Sync platform SR status when an existing SR ID is present in session state.

Responsibilities
----------------
- When ``backend_refs["sr_id"]`` is populated, call GET /service-requests/{sr_id}
  via the SR API service to fetch the current platform status.
- Map ``service_request_operations`` to a ``workflow_stage`` value:
    - Any FM_MANAGER or OPERATIONS operation with IN_PROGRESS  → "FM_REVIEW"
    - Any DD_ENGINEER operation with IN_PROGRESS               → "RDD_REVIEW"
    - All operations FINISHED/APPROVED                         → "SR_COMPLETED"
    - No operations / unknown                                  → unchanged
- Write results back to ``backend_refs``:
    - ``platform_sr_status``     — raw status string from the API
    - ``sr_operations``          — the operations list
- Update ``workflow_stage`` in state when a new stage is detected.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT submit or modify any SR data.
- Skipped when ``sr_id`` is absent (pure CREATE_SR path with no existing SR).
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

from app.agents.graph.state import ServiceRequestState
from app.agents.services.service_request_api_service import get_service_request_api_service
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)
logger = logging.getLogger(__name__)

# Role strings that indicate FM review in the operations list.
_FM_ROLES: frozenset[str] = frozenset({"FM_MANAGER", "OPERATIONS"})
_RDD_ROLES: frozenset[str] = frozenset({"DD_ENGINEER"})
_TERMINAL_STATUSES: frozenset[str] = frozenset({"FINISHED", "APPROVED", "COMPLETED", "DONE"})


def _map_operations_to_stage(
    operations: list[dict[str, Any]],
    current_stage: str | None,
) -> str | None:
    """Derive workflow_stage from ``service_request_operations`` list.

    Priority: RDD_REVIEW > FM_REVIEW > SR_COMPLETED > unchanged.
    """
    if not operations:
        return current_stage

    in_progress_roles: set[str] = set()
    any_terminal = True

    for op in operations:
        status = (op.get("status") or "").upper()
        # Platform returns "assigned_role"; fall back to "role" for flexibility.
        role = (op.get("assigned_role") or op.get("role") or "").upper()
        if status == "IN_PROGRESS":
            in_progress_roles.add(role)
            any_terminal = False
        elif status not in _TERMINAL_STATUSES:
            any_terminal = False

    if _RDD_ROLES & in_progress_roles:
        return "RDD_REVIEW"
    if _FM_ROLES & in_progress_roles:
        return "FM_REVIEW"
    if any_terminal:
        return "SR_COMPLETED"

    return current_stage


@trace_node("sr_status_sync", "TOOL")
async def sr_status_sync_node(state: ServiceRequestState) -> dict[str, Any]:
    """Fetch platform SR status and update workflow_stage in state.

    Reads from state
    ----------------
    ``backend_refs``  — must contain ``sr_id`` to trigger a sync.
    ``workflow_stage`` — current stage; updated when platform status differs.

    Writes to state
    ---------------
    ``backend_refs``   — enriched with ``platform_sr_status`` and ``sr_operations``.
    ``workflow_stage`` — updated to FM_REVIEW, RDD_REVIEW, or SR_COMPLETED when
                         the platform operations warrant it.
    """
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    sr_id: str | None = backend_refs.get("sr_id")

    if not sr_id:
        logger.debug("sr_status_sync_node: skipped — no sr_id in backend_refs")
        return {}

    current_stage: str | None = state.get("workflow_stage")
    svc = get_service_request_api_service()

    try:
        result = await svc.get_service_request(sr_id)
    except Exception as exc:
        logger.warning(
            "sr_status_sync_node: get_service_request raised %s — continuing with cached stage",
            exc,
            exc_info=True,
        )
        return {}

    if result.error:
        logger.warning(
            "sr_status_sync_node: GET sr_id=%s error=%s status_code=%s — continuing",
            sr_id,
            result.error,
            result.status_code,
        )
        return {}

    # Support both ServiceRequestGetResult (has .status / .service_request_operations)
    # and the legacy ServiceRequestCreationResult (stores data in .response_payload).
    platform_status: str | None = getattr(result, "status", None)
    operations: list[dict[str, Any]] = list(getattr(result, "service_request_operations", None) or [])

    if not platform_status or not operations:
        # Fall back to response_payload for legacy / test mock shapes that use
        # _sr_status and _service_request_operations as envelope keys.
        response_payload: dict[str, Any] = getattr(result, "response_payload", None) or {}
        if not platform_status:
            platform_status = (
                response_payload.get("_sr_status")
                or response_payload.get("status")
            )
        if not operations:
            operations = (
                response_payload.get("_service_request_operations")
                or response_payload.get("service_request_operations")
                or []
            )

    new_stage = _map_operations_to_stage(operations, current_stage)

    backend_refs["platform_sr_status"] = platform_status
    backend_refs["sr_operations"] = operations

    log.info(
        "sr_status_sync_node.done",
        sr_id=sr_id,
        platform_status=platform_status,
        current_stage=current_stage,
        new_stage=new_stage,
        operations_count=len(operations),
    )

    updates: dict[str, Any] = {"backend_refs": backend_refs}
    if new_stage and new_stage != current_stage:
        updates["workflow_stage"] = new_stage

    return updates
