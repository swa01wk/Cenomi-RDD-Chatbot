"""Build the PATCH payload for FM_REVIEW save-progress or approval.

Responsibilities
----------------
- Read ``backend_refs["fm_action"]`` to determine whether to build a
  save-progress payload (``"save_progress"``) or an approval payload (``"approve"``).
- Delegate to ``build_fm_review_payload`` or ``build_fm_approve_payload``.
- Store the result in ``backend_refs["fm_payload"]``.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT submit to the platform (that is ``fm_api_submission_node``).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.services.payload_builder_service import (
    build_fm_approve_payload,
    build_fm_review_payload,
)
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)


@trace_node("fm_payload_builder", "AGENT")
async def fm_payload_builder_node(state: ServiceRequestState) -> dict[str, Any]:
    """Build the FM_REVIEW PATCH payload and store it in backend_refs.

    Reads from state
    ----------------
    ``collected_data``              — must contain FM fields (dates).
    ``backend_refs``                — must contain ``sr_id``, ``create_payload``,
                                      ``uploaded_documents``, ``fm_action``.

    Writes to state
    ---------------
    ``backend_refs["fm_payload"]``  — the built PATCH payload.
    ``status``                      — ``"FAILED"`` when payload cannot be built.
    ``response_message``            — set on failure.
    """
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})
    fm_action: str = backend_refs.get("fm_action", "save_progress")

    sr_id: str | None = backend_refs.get("sr_id")
    if not sr_id:
        logger.warning("fm_payload_builder_node: blocked — sr_id missing from backend_refs")
        return {
            "status": "FAILED",
            "response_message": (
                "Cannot build FM payload: service request ID is not available. "
                "Please try again."
            ),
        }

    try:
        if fm_action == "approve":
            comment: str = collected_data.get("fm_comment", "")
            payload = build_fm_approve_payload(collected_data, backend_refs, comment)
        else:
            payload = build_fm_review_payload(collected_data, backend_refs)
    except Exception as exc:
        logger.warning("fm_payload_builder_node: payload build failed — %s", exc, exc_info=True)
        return {
            "status": "FAILED",
            "response_message": (
                f"Could not build the FM review payload: {exc}. "
                "Please check the uploaded documents and dates."
            ),
        }

    backend_refs["fm_payload"] = payload
    logger.info(
        "fm_payload_builder_node: payload built for sr_id=%s fm_action=%s",
        sr_id,
        fm_action,
    )
    return {"backend_refs": backend_refs}
