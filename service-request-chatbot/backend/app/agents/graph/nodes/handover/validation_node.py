"""Validate draft using code + schemas — not the LLM.

This node runs all deterministic validation rules against ``collected_data``
and updates two state fields:

* ``validation_errors`` — list of FAILED ``ValidationResult`` dicts (see
  ``validation_service.py`` for the canonical shape).
* ``status`` — set to ``"READY_TO_SUBMIT"`` when there are no blocking errors,
  or kept at ``"IN_PROGRESS"`` when blocking errors must be resolved first.

Responsibilities
----------------
* Invoke ``ValidationService.validate_draft()`` for the current workflow stage.
* Populate ``state.validation_errors`` with all FAILED validation results.
* Set ``state.status`` based on whether any blocking errors were found.
* Log a traceable summary (stage, total failures, blocking count).

Non-responsibilities
--------------------
* Does not call the LLM.
* Does not collect missing fields (that is ``missing_field_node``'s job).
* Does not submit the service request (that is ``api_submission_node``'s job).
* Does not generate a user-facing response message (that is
  ``response_generation_node``'s job).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.services.validation_service import ValidationService
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)

_validation_service = ValidationService()


@trace_node("validation", "AGENT")
async def validation_node(state: ServiceRequestState) -> dict[str, Any]:
    """Run deterministic validation; update ``validation_errors`` and ``status``.

    Reads from state
    ----------------
    ``collected_data``  — the draft field values to validate.
    ``workflow_stage``  — determines which required fields and document types apply.
    ``documents``       — uploaded documents whose types must be validated.
    ``role``            — optional user role for permission hook (not in TypedDict;
                          injected at runtime by the API layer when available).

    Writes to state
    ---------------
    ``validation_errors`` — list of FAILED ValidationResult dicts; empty when all
                            rules pass.
    ``status``            — ``"READY_TO_SUBMIT"`` (no blocking errors) or
                            ``"IN_PROGRESS"`` (blocking errors present).
    """
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    workflow_stage: str = state.get("workflow_stage") or "CREATE_SR"
    documents: list[dict] = state.get("documents") or []
    role: str | None = state.get("role")  # type: ignore[arg-type]

    validation_errors = _validation_service.validate_draft(
        data=collected_data,
        workflow_stage=workflow_stage,
        documents=documents,
        role=role,
    )

    blocking_errors = [e for e in validation_errors if e["blocking"]]
    has_blocking = len(blocking_errors) > 0

    logger.info(
        "validation_node: stage=%s total_errors=%d blocking_errors=%d",
        workflow_stage,
        len(validation_errors),
        len(blocking_errors),
    )

    new_status: str = "IN_PROGRESS" if has_blocking else "READY_TO_SUBMIT"

    return {
        "validation_errors": validation_errors,
        "status": new_status,
    }
