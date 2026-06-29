"""Partition uploaded documents into FM and RDD buckets in backend_refs.

Responsibilities
----------------
- Read state["documents"] — a list of document metadata dicts, each with
  at least ``document_id`` and ``document_type_id`` keys.
- FM documents (SR_HANDOVER_CHECKLIST, SR_HANDOVER_SITE_SURVEY,
  SR_COP_CHECKLIST_OTHER, SR_HANDOVER_OTHER) → merged into
  ``backend_refs["uploaded_documents"]`` (deduplicated, preserving pre-existing IDs).
- RDD report (DR_SR_HANDOVER_REPORT) → stored as
  ``backend_refs["rdd_document_id"]`` (last one wins).
- Documents with None or missing ``document_id`` are silently skipped.
- Unknown document types are silently ignored (neither FM nor RDD bucket).

Non-responsibilities
--------------------
- Does not call the platform upload API — that is handled by the upload HTTP route.
- Does not call the LLM.
- Returns only ``backend_refs`` — no other state keys are mutated.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState

logger = logging.getLogger(__name__)

# Document type sets
_FM_DOCUMENT_TYPES: frozenset[str] = frozenset({
    "SR_HANDOVER_CHECKLIST",
    "SR_HANDOVER_SITE_SURVEY",
    "SR_COP_CHECKLIST_OTHER",
    "SR_HANDOVER_OTHER",
})

_RDD_DOCUMENT_TYPE = "DR_SR_HANDOVER_REPORT"


async def document_upload_node(state: ServiceRequestState) -> dict[str, Any]:
    """Partition state["documents"] into FM and RDD buckets in backend_refs."""
    documents: list[dict[str, Any]] = state.get("documents") or []  # type: ignore[assignment]
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})

    # Start from any pre-existing uploaded_documents (merge, don't replace)
    existing_fm_ids: list[str] = list(backend_refs.get("uploaded_documents") or [])
    fm_ids_set: set[str] = set(existing_fm_ids)

    rdd_document_id: str | None = backend_refs.get("rdd_document_id")

    for doc in documents:
        doc_id: str | None = doc.get("document_id")
        doc_type: str = doc.get("document_type_id") or ""

        if not doc_id:
            continue

        if doc_type in _FM_DOCUMENT_TYPES:
            if doc_id not in fm_ids_set:
                fm_ids_set.add(doc_id)
                existing_fm_ids.append(doc_id)
        elif doc_type == _RDD_DOCUMENT_TYPE:
            rdd_document_id = doc_id

    updated_refs: dict[str, Any] = {
        **backend_refs,
        "uploaded_documents": existing_fm_ids,
    }
    if rdd_document_id is not None:
        updated_refs["rdd_document_id"] = rdd_document_id

    logger.info(
        "document_upload_node: fm_docs=%d rdd_doc=%s",
        len(existing_fm_ids),
        rdd_document_id,
    )

    return {"backend_refs": updated_refs}
