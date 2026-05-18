"""Build upstream API payloads for Handover Service Request workflows.

Public functions
----------------
- ``build_create_handover_payload``  — CREATE_SR (Mall Manager POST)
- ``build_fm_review_payload``        — FM_REVIEW save-progress (PATCH IN_PROCESS)
- ``build_fm_approve_payload``       — FM_REVIEW approval (PATCH APPROVED)
- ``build_rdd_report_payload``       — RDD_REVIEW submit report (POST REPORT_SUBMITTED)

Design notes
------------
* Pure deterministic data mapping — no LLM calls, no I/O.
* Required keys are validated before the payload dict is returned; any
  missing key raises ``ValueError`` with a descriptive message so callers
  can surface the error before attempting a network call.
* ``startDateLT`` and ``endDateLT`` are timezone-localised date variants
  optionally enriched by the lease-lookup flow; they default to ``""`` when absent.
* RDD date values from collected_data are in ISO format (YYYY-MM-DD); they
  are normalised to DD/MM/YYYY per the Postman collection shape.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Required data keys ────────────────────────────────────────────────────────

# Every key in this set must be present (non-None, non-"", non-[]) in the
# ``data`` dict passed to ``build_create_handover_payload``.
# Optional fields such as "comments" and "notes" are intentionally excluded:
# they may be empty strings when the user declines to provide them, and the
# upstream API accepts an empty string for those fields.
_REQUIRED_DATA_KEYS: frozenset[str] = frozenset(
    {
        "mall",
        "brand",
        "lease_code",
        "title",
        "endDate",
        "startDate",
        "description",
        "inspection_done_by",
        "lease_brand_mall",
        "unit_codes",
        "contracted_area",
        "city",
        "brand_id",
        "tenant_profile_id",
        "contract_id",
        "property_id",
        "lease_id",
    }
)

# ── Internal helpers ───────────────────────────────────────────────────────────


def _validate_required_keys(data: dict[str, Any]) -> None:
    """Raise ``ValueError`` when any required key is absent or empty.

    Absence means: the key is missing from *data*, or its value is ``None``,
    ``""``, or ``[]``.  Integer ``0`` and boolean ``False`` are valid values.
    """
    missing: list[str] = [
        key
        for key in sorted(_REQUIRED_DATA_KEYS)
        if (lambda v: v is None or v == "" or v == [])(data.get(key))
    ]

    if missing:
        raise ValueError(
            f"build_create_handover_payload: missing required data keys: {missing}"
        )


# ── Public API ────────────────────────────────────────────────────────────────


def build_create_handover_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Build the CREATE_SR submission payload from validated ``collected_data``.

    Parameters
    ----------
    data:
        The validated ``collected_data`` dict from the graph state.  All keys
        listed in ``_REQUIRED_DATA_KEYS`` must be present and non-empty.

    Returns
    -------
    dict
        The complete payload ready for the Handover Service Request API.
        ``service_request_id`` is set to ``""`` for new requests (the backend
        assigns an ID on creation).

    Raises
    ------
    ValueError
        If any required key is absent or empty in *data*.
    """
    _validate_required_keys(data)

    payload: dict[str, Any] = {
        "payload": {
            "mall": data["mall"],
            "brand": data["brand"],
            "lease": data["lease_code"],
            "notes": data.get("notes", ""),
            "title": data["title"],
            "endDate": data["endDate"],
            "comments": data.get("comments", ""),
            "startDate": data["startDate"],
            "attachments": "",
            "description": data["description"],
            "documents_ids": [],
            "guideLineLink": "",
            "inspectionDoneBy": data["inspection_done_by"],
            "lease_brand_mall": data["lease_brand_mall"],
            "inspection_done_by": data["inspection_done_by"],
            "document_status_map": [],
            "unit_readiness_date": "",
            "expected_handover_date": "",
            "company_name": str(data["tenant_profile_id"]),
            "tenant_contact": "",
            "user_action": None,
            "unit_codes": data["unit_codes"],
            "contracted_area": data["contracted_area"],
            "city": data["city"],
            "brand_id": data["brand_id"],
            "tenant_profile_id": data["tenant_profile_id"],
            "contract_id": data["contract_id"],
            "property_id": data["property_id"],
            # Timezone-localised date variants; optional — default to "" when absent.
            "startDateLT": data.get("startDateLT", ""),
            "endDateLT": data.get("endDateLT", ""),
        },
        "title": data["title"],
        "tenant_profile_id": data["tenant_profile_id"],
        "property_id": data["property_id"],
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "lease_code": data["lease_code"],
        "lease_id": data["lease_id"],
        "service_request_id": "",
    }

    logger.debug(
        "build_create_handover_payload: payload built for lease_code=%s tenant_profile_id=%s",
        data["lease_code"],
        data["tenant_profile_id"],
    )

    return payload


# ── FM / RDD payload builders ─────────────────────────────────────────────────


def _to_ddmmyyyy(iso_date_str: str) -> str:
    """Convert ``"YYYY-MM-DD"`` to ``"DD/MM/YYYY"``.

    Returns the input unchanged when it cannot be parsed (best-effort).
    """
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(iso_date_str, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return iso_date_str


def _fm_document_status_entry(doc_id: str) -> dict[str, Any]:
    """Build a single document_status_map entry for an FM document."""
    return {
        "id": doc_id,
        "document_status": "",
        "handover_date": "",
        "actual_handover_date": "",
        "fitout_start_date": "",
        "fitout_end_date": "",
        "trading_date": "",
    }


def _rdd_document_status_entry(
    doc_id: str,
    actual_handover_date: str = "",
    fitout_start_date: str = "",
    fitout_end_date: str = "",
    trading_date: str = "",
) -> dict[str, Any]:
    """Build a document_status_map entry for the RDD handover report."""
    return {
        "id": doc_id,
        "document_status": "APPROVED",
        "handover_date": "",
        "actual_handover_date": _to_ddmmyyyy(actual_handover_date) if actual_handover_date else "",
        "fitout_start_date": _to_ddmmyyyy(fitout_start_date) if fitout_start_date else "",
        "fitout_end_date": _to_ddmmyyyy(fitout_end_date) if fitout_end_date else "",
        "trading_date": _to_ddmmyyyy(trading_date) if trading_date else "",
    }


def build_fm_review_payload(
    data: dict[str, Any],
    backend_refs: dict[str, Any],
) -> dict[str, Any]:
    """Build the PATCH payload for FM_REVIEW save-progress (status=IN_PROCESS).

    Parameters
    ----------
    data:
        ``collected_data`` from graph state; must include ``unit_readiness_date``
        and ``expected_handover_date``.
    backend_refs:
        ``backend_refs`` from graph state; must include ``sr_id``,
        ``create_payload``, ``uploaded_documents`` (list of document UUIDs),
        and ``sr_operations``.

    Returns
    -------
    dict
        Full PATCH body ready for ``PlatformAPIClient.patch_service_request``.
    """
    sr_id: str = backend_refs.get("sr_id", "")
    create_payload: dict[str, Any] = backend_refs.get("create_payload") or {}
    inner: dict[str, Any] = create_payload.get("payload") or {}

    uploaded_docs: list[str] = backend_refs.get("uploaded_documents") or []
    sr_operations: list[dict[str, Any]] = backend_refs.get("sr_operations") or []
    ref_no: str = backend_refs.get("ref_no", "")

    document_status_map = [_fm_document_status_entry(doc_id) for doc_id in uploaded_docs]

    fm_inner: dict[str, Any] = {
        **inner,
        "unit_readiness_date": data.get("unit_readiness_date", ""),
        "expected_handover_date": data.get("expected_handover_date", ""),
        "documents_ids": uploaded_docs,
        "document_status_map": document_status_map,
        "ref_no": ref_no,
        "sr_id": sr_id,
        "current_sr_status": "IN_PROCESS",
        "document_saved": True,
        "sr_operations": sr_operations,
        "user_action": None,
    }

    payload: dict[str, Any] = {
        "payload": fm_inner,
        "title": inner.get("title", data.get("title", "")),
        "tenant_profile_id": inner.get("tenant_profile_id", data.get("tenant_profile_id")),
        "property_id": inner.get("property_id", data.get("property_id")),
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "lease_code": inner.get("lease", data.get("lease_code", "")),
        "lease_id": create_payload.get("lease_id", data.get("lease_id")),
        "service_request_id": sr_id,
        "status": "IN_PROCESS",
    }

    logger.debug(
        "build_fm_review_payload: built for sr_id=%s uploaded_docs=%d",
        sr_id,
        len(uploaded_docs),
    )
    return payload


def build_fm_approve_payload(
    data: dict[str, Any],
    backend_refs: dict[str, Any],
    comment: str = "",
) -> dict[str, Any]:
    """Build the PATCH payload for FM_REVIEW approval (status=APPROVED).

    Same shape as save-progress but with ``status="APPROVED"`` and an
    optional ``comment`` field.  Top-level ``lease_code``/``lease_id`` are
    omitted per the Postman collection shape for approval.
    """
    base = build_fm_review_payload(data, backend_refs)

    sr_id: str = backend_refs.get("sr_id", "")
    uploaded_docs: list[str] = backend_refs.get("uploaded_documents") or []
    inner = dict(base.get("payload") or {})
    inner["current_sr_status"] = "APPROVED"
    if comment:
        inner["comment"] = comment

    return {
        "payload": inner,
        "title": base.get("title", ""),
        "tenant_profile_id": base.get("tenant_profile_id"),
        "property_id": base.get("property_id"),
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "service_request_id": sr_id,
        "status": "APPROVED",
    }


def build_rdd_report_payload(
    data: dict[str, Any],
    backend_refs: dict[str, Any],
) -> dict[str, Any]:
    """Build the POST payload for RDD_REVIEW submit-report (status=REPORT_SUBMITTED).

    Parameters
    ----------
    data:
        ``collected_data`` from graph state; must include the four RDD date
        fields (``actual_handover_date``, ``fitout_start_date``,
        ``fitout_end_date``, ``trading_date``) and ``guideLineLink``.
    backend_refs:
        ``backend_refs`` from graph state; must include ``sr_id``,
        ``create_payload``, ``uploaded_documents`` (FM doc IDs), and
        ``rdd_document_id`` (the RDD report doc UUID).

    Returns
    -------
    dict
        Full POST body ready for ``PlatformAPIClient.submit_report``.
    """
    sr_id: str = backend_refs.get("sr_id", "")
    create_payload: dict[str, Any] = backend_refs.get("create_payload") or {}
    inner: dict[str, Any] = create_payload.get("payload") or {}

    fm_doc_ids: list[str] = backend_refs.get("uploaded_documents") or []
    rdd_doc_id: str | None = backend_refs.get("rdd_document_id")

    all_doc_ids = list(fm_doc_ids)
    if rdd_doc_id and rdd_doc_id not in all_doc_ids:
        all_doc_ids.append(rdd_doc_id)

    fm_status_map = [_fm_document_status_entry(doc_id) for doc_id in fm_doc_ids]
    rdd_status_entry = (
        _rdd_document_status_entry(
            doc_id=rdd_doc_id,
            actual_handover_date=data.get("actual_handover_date", ""),
            fitout_start_date=data.get("fitout_start_date", ""),
            fitout_end_date=data.get("fitout_end_date", ""),
            trading_date=data.get("trading_date", ""),
        )
        if rdd_doc_id
        else None
    )
    document_status_map = fm_status_map + ([rdd_status_entry] if rdd_status_entry else [])

    rdd_inner: dict[str, Any] = {
        **inner,
        "guideLineLink": data.get("guideLineLink", ""),
        "documents_ids": all_doc_ids,
        "document_status_map": document_status_map,
        "unit_readiness_date": data.get("unit_readiness_date", inner.get("unit_readiness_date", "")),
        "expected_handover_date": data.get(
            "expected_handover_date", inner.get("expected_handover_date", "")
        ),
        "sr_id": sr_id,
        "user_action": None,
    }

    payload: dict[str, Any] = {
        "payload": rdd_inner,
        "title": inner.get("title", data.get("title", "")),
        "tenant_profile_id": inner.get("tenant_profile_id", data.get("tenant_profile_id")),
        "property_id": inner.get("property_id", data.get("property_id")),
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "lease_code": inner.get("lease", data.get("lease_code", "")),
        "lease_id": create_payload.get("lease_id", data.get("lease_id")),
        "service_request_id": sr_id,
        "status": "REPORT_SUBMITTED",
    }

    logger.debug(
        "build_rdd_report_payload: built for sr_id=%s fm_docs=%d rdd_doc=%s",
        sr_id,
        len(fm_doc_ids),
        rdd_doc_id,
    )
    return payload


# ── PayloadBuilderService class (DI / backward-compatible wrapper) ────────────


class PayloadBuilderService:
    """Thin class wrapper around the module-level payload builder functions.

    Use the module-level functions directly where possible.  This class
    exists for dependency-injection patterns and backward compatibility.
    """

    def build(self, draft: dict[str, object]) -> dict[str, object]:
        """Backward-compatible passthrough (does not validate or transform)."""
        return dict(draft)

    def build_create_handover_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        """Delegate to the module-level ``build_create_handover_payload``."""
        return build_create_handover_payload(data)

    def build_fm_review_payload(
        self, data: dict[str, Any], backend_refs: dict[str, Any]
    ) -> dict[str, Any]:
        return build_fm_review_payload(data, backend_refs)

    def build_fm_approve_payload(
        self,
        data: dict[str, Any],
        backend_refs: dict[str, Any],
        comment: str = "",
    ) -> dict[str, Any]:
        return build_fm_approve_payload(data, backend_refs, comment)

    def build_rdd_report_payload(
        self, data: dict[str, Any], backend_refs: dict[str, Any]
    ) -> dict[str, Any]:
        return build_rdd_report_payload(data, backend_refs)
