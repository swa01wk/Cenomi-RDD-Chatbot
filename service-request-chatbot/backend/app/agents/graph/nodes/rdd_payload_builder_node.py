"""Build the POST payload for RDD_REVIEW report submission.

Responsibilities
----------------
- Delegate to ``build_rdd_report_payload`` from payload_builder_service.
- Store the result in ``backend_refs["rdd_payload"]``.

Non-responsibilities
--------------------
- MUST NOT call the LLM.
- MUST NOT submit to the platform (that is ``rdd_api_submission_node``).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.services.payload_builder_service import build_rdd_report_payload
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)


@trace_node("rdd_payload_builder", "AGENT")
async def rdd_payload_builder_node(state: ServiceRequestState) -> dict[str, Any]:
    """Build the RDD report submission payload and store it in backend_refs.

    Reads from state
    ----------------
    ``collected_data``              — must contain date fields and guideLineLink.
    ``backend_refs``                — must contain ``sr_id``, ``create_payload``,
                                      ``uploaded_documents``, ``rdd_document_id``.

    Writes to state
    ---------------
    ``backend_refs["rdd_payload"]`` — the built POST payload.
    ``status``                      — ``"FAILED"`` when payload cannot be built.
    ``response_message``            — set on failure.
    """
    collected_data: dict[str, Any] = state.get("collected_data") or {}
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})

    sr_id: str | None = backend_refs.get("sr_id")
    if not sr_id:
        logger.warning("rdd_payload_builder_node: blocked — sr_id missing from backend_refs")
        return {
            "status": "FAILED",
            "response_message": (
                "Cannot build RDD report payload: service request ID is not available."
            ),
        }

    try:
        payload = build_rdd_report_payload(collected_data, backend_refs)
    except Exception as exc:
        logger.warning(
            "rdd_payload_builder_node: payload build failed — %s", exc, exc_info=True
        )
        return {
            "status": "FAILED",
            "response_message": (
                f"Could not build the RDD report payload: {exc}. "
                "Please ensure all date fields and the report document are provided."
            ),
        }

    backend_refs["rdd_payload"] = payload
    logger.info("rdd_payload_builder_node: payload built for sr_id=%s", sr_id)
    return {"backend_refs": backend_refs}
