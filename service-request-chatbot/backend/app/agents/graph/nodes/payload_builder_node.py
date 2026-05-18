"""Build API payload from validated draft.

Responsibilities
----------------
* For the CREATE_SR stage: call ``build_create_handover_payload`` with the
  current ``collected_data`` and store the result in ``backend_refs``.
* Guard against missing required fields by catching ``ValueError`` from the
  payload builder and setting ``status = "FAILED"``.

Non-responsibilities
--------------------
* Does not call the LLM.
* Does not submit the payload to the API (that is ``api_submission_node``).
* Does not handle FM_REVIEW or RDD_REVIEW payload shapes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.services.payload_builder_service import build_create_handover_payload
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)


@trace_node("payload_builder", "TOOL")
async def payload_builder_node(state: ServiceRequestState) -> dict[str, Any]:
    """Build the CREATE_SR API payload and store it in ``backend_refs``.

    Reads from state
    ----------------
    ``collected_data``  — validated draft field values.
    ``workflow_stage``  — only acts for ``"CREATE_SR"``; skips other stages.

    Writes to state
    ---------------
    ``backend_refs``    — updated with ``{"create_payload": <payload dict>}``.
    ``status``          — set to ``"FAILED"`` if required keys are missing.
    """
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    workflow_stage: str = state.get("workflow_stage") or "CREATE_SR"

    if workflow_stage != "CREATE_SR":
        logger.info(
            "payload_builder_node: skipped for stage=%s (only handles CREATE_SR)",
            workflow_stage,
        )
        return {}

    try:
        payload = build_create_handover_payload(collected_data)
    except ValueError as exc:
        logger.warning("payload_builder_node: payload build failed — %s", exc)
        return {"status": "FAILED"}

    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    backend_refs["create_payload"] = payload

    logger.info(
        "payload_builder_node: payload built for lease_code=%s",
        collected_data.get("lease_code"),
    )

    return {"backend_refs": backend_refs}
