"""Bridge uploaded document IDs from state["documents"] into backend_refs.

Reads state["documents"] (list of {document_id, document_type_id, ...} written by
POST /api/upload → draft.documents → load_session_node → state["documents"]).

Partitions by document type:
  FM docs (SR_HANDOVER_CHECKLIST, SR_HANDOVER_SITE_SURVEY, SR_COP_CHECKLIST_OTHER)
    → backend_refs["uploaded_documents"]  (consumed by fm_payload_builder)
  RDD report (DR_SR_HANDOVER_REPORT)
    → backend_refs["rdd_document_id"]     (consumed by rdd_payload_builder)

This is a pure state bridge — no API calls, no LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.agents.schemas.handover_schema import FM_ALLOWED_DOCUMENTS, RDD_REQUIRED_DOCUMENTS
from app.observability.decorators import trace_node

logger = logging.getLogger(__name__)


@trace_node("document_upload", "CHAIN")
async def document_upload_node(state: ServiceRequestState) -> dict[str, Any]:
    """Partition uploaded document IDs into the correct backend_refs slots."""
    documents: list[dict] = state.get("documents") or []
    backend_refs: dict[str, Any] = dict(state.get("backend_refs") or {})

    fm_doc_ids: list[str] = []
    rdd_doc_id: str | None = None

    for doc in documents:
        doc_type = doc.get("document_type_id", "")
        doc_id = doc.get("document_id")
        if not doc_id:
            continue
        if doc_type in FM_ALLOWED_DOCUMENTS:
            if doc_id not in fm_doc_ids:
                fm_doc_ids.append(doc_id)
        elif doc_type in RDD_REQUIRED_DOCUMENTS:
            rdd_doc_id = doc_id  # last wins — single report expected

    # Merge with any IDs already set from prior turns
    existing_fm: list[str] = backend_refs.get("uploaded_documents") or []
    merged_fm: list[str] = list(dict.fromkeys(existing_fm + fm_doc_ids))
    backend_refs["uploaded_documents"] = merged_fm

    if rdd_doc_id:
        backend_refs["rdd_document_id"] = rdd_doc_id

    logger.debug(
        "document_upload_node: fm_docs=%d rdd_doc=%s",
        len(merged_fm),
        rdd_doc_id,
    )

    return {"backend_refs": backend_refs}
