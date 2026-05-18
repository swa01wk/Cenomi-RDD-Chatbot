"""Lease lookup node — resolves lease/tenant identity and enriches collected_data.

Responsibilities
----------------
- Detect lease-identifying signals in ``collected_data`` (lease_code, brand, mall).
- Delegate the actual API call to ``AbstractLeaseLookupService``.
- Trace every external call as a ``TOOL_CALL`` child run via ``TraceManager``.
- Handle three match outcomes:
    0 matches  → ask user for more details (WAITING_FOR_USER).
    1 match    → auto-enrich ``collected_data`` with backend-derived fields.
    N matches  → surface choices via ``response_ui.type = "lease_selection"``.
- Merge a user-selected lease (``selected_lease``) when one is already present.

Non-responsibilities (enforced)
--------------------------------
- MUST NOT call the LLM.
- MUST NOT modify fields that are not backend-derived (title, description, dates, …).
- MUST NOT overwrite backend-derived fields from LLM extraction; only this node
  (and backend API responses) may populate ``BACKEND_PROTECTED_FIELDS``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from app.agents.graph.nodes.merge_state_node import BACKEND_PROTECTED_FIELDS
from app.agents.graph.state import ServiceRequestState
from app.agents.services.lease_lookup_service import (
    AbstractLeaseLookupService,
    LeaseRecord,
    LeaseLookupQuery,
    get_lease_lookup_service,
)
from app.observability.decorators import trace_node

log = structlog.get_logger(__name__)

# Fields from ``LeaseRecord`` that are written directly into ``collected_data``.
# This is a strict superset of BACKEND_PROTECTED_FIELDS (which only lists the
# IDs/codes that must never come from LLM extraction).
_LEASE_ENRICHMENT_FIELDS: frozenset[str] = frozenset(
    {
        "lease_code",
        "lease_id",
        "contract_id",
        "brand",
        "brand_id",
        "mall",
        "property_id",
        "tenant_profile_id",
        "unit_codes",
        "contracted_area",
        "city",
        "lease_brand_mall",
    }
)

_NO_LEASE_FIELDS_MESSAGE = (
    "No lease identifiers were found. Ask the user for the lease code, "
    "or alternatively the brand name and/or mall name."
)
_NO_MATCH_MESSAGE = (
    "The lease lookup returned zero matches. Apologise and ask the user to "
    "double-check the lease code, brand name, or mall name they provided."
)
_MULTI_MATCH_MESSAGE = (
    "Multiple leases matched the search. Ask the user to select the correct one "
    "from the list shown."
)


def _extract_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _enrich_collected_data(
    collected: dict[str, Any],
    record: LeaseRecord,
) -> dict[str, Any]:
    """Return a new dict with backend-derived fields merged from *record*."""
    updated = dict(collected)
    for field_name in _LEASE_ENRICHMENT_FIELDS:
        updated[field_name] = getattr(record, field_name)
    return updated


@trace_node("lease_lookup", "LANGGRAPH_NODE")
async def lease_lookup_node(
    state: ServiceRequestState,
    service: AbstractLeaseLookupService | None = None,
) -> dict[str, Any]:
    """LangGraph node: resolve lease identity and enrich draft state.

    Parameters
    ----------
    state:
        Current graph state.
    service:
        Optional ``AbstractLeaseLookupService`` override (injected in tests).
        Production code uses ``get_lease_lookup_service()``.
    """
    tm = state.get("trace_manager")
    trace_id: UUID | None = _extract_uuid(state.get("trace_id"))

    collected: dict[str, Any] = dict(state.get("collected_data") or {})
    lookup_service = service or get_lease_lookup_service()

    # ── Path A: user has already selected a lease from a multi-match list ─────
    selected_lease: dict[str, Any] | None = state.get("selected_lease")
    if selected_lease:
        record: LeaseRecord | None = None
        try:
            record = LeaseRecord.model_validate(selected_lease)
        except Exception as exc:
            # The API boundary passes only {"id": "<lease_code>"} — a partial
            # hint rather than a full LeaseRecord.  Extract whatever identifier
            # is available and fall through to Path B for a fresh lookup.
            fallback_code = (
                selected_lease.get("lease_code") or selected_lease.get("id")
            )
            if fallback_code:
                log.info(
                    "lease_lookup.selected_lease.fallback_to_lookup",
                    fallback_code=fallback_code,
                )
                collected["lease_code"] = fallback_code
                # record remains None → fall through to Path B below
            else:
                log.warning("lease_lookup.selected_lease.invalid", error=str(exc))
                return {
                    "status": "WAITING_FOR_USER",
                    "response_message": (
                        "The selected lease could not be validated due to a data error. "
                        "Apologise and ask the user to try selecting again or provide the lease code."
                    ),
                    "response_ui": {
                        "type": "text_question",
                        "field": "lease_code",
                        "message": _NO_LEASE_FIELDS_MESSAGE,
                    },
                }

        if record is not None:
            enriched = _enrich_collected_data(collected, record)
            log.info(
                "lease_lookup.selected_lease.merged",
                lease_code=record.lease_code,
            )
            return {
                "collected_data": enriched,
                "lease_matches": [],
                "selected_lease": None,
                "status": "IN_PROGRESS",
            }
        # Fall through to Path B with collected["lease_code"] set from fallback_code

    # ── Path B: no lease yet selected — run lookup ────────────────────────────
    # Normalise lease_code: strip whitespace and lowercase so that inputs like
    # "T0105712" or "t0 105712" match the canonical lowercase codes in the DB.
    raw_lease_code: str | None = collected.get("lease_code")
    normalised_lease_code: str | None = (
        raw_lease_code.strip().lower().replace(" ", "") if raw_lease_code else None
    )
    query = LeaseLookupQuery(
        lease_code=normalised_lease_code,
        brand=collected.get("brand"),
        mall=collected.get("mall"),
    )

    if not query.has_identifiers():
        log.info("lease_lookup.no_identifiers")
        return {
            "status": "WAITING_FOR_USER",
            "response_message": _NO_LEASE_FIELDS_MESSAGE,
            "response_ui": {
                "type": "text_question",
                "field": "lease_code",
                "message": _NO_LEASE_FIELDS_MESSAGE,
            },
        }

    # ── Open a child TOOL run span ────────────────────────────────────────────
    tool_run_id: UUID | None = None
    if tm is not None and trace_id is not None:
        try:
            tool_run_id = await tm.start_run(
                trace_id=trace_id,
                run_name="lease_api_call",
                run_type="TOOL",
            )
        except Exception:
            log.warning("lease_lookup.start_tool_run.failed", exc_info=True)

    # ── Call the service ──────────────────────────────────────────────────────
    result = await lookup_service.lookup(query)

    # ── Record tool call ──────────────────────────────────────────────────────
    if tm is not None and trace_id is not None and tool_run_id is not None:
        try:
            await tm.capture_tool_call(
                trace_id=trace_id,
                run_id=tool_run_id,
                tool_name="lease_tenant_api",
                tool_type="HTTP",
                request_payload={
                    "endpoint": result.endpoint,
                    **query.model_dump(exclude_none=True),
                },
                response_payload=result.response_payload,
                status_code=result.status_code,
                success=result.error is None,
                latency_ms=result.latency_ms,
                error_message=result.error,
            )
        except Exception:
            log.warning("lease_lookup.capture_tool_call.failed", exc_info=True)

        try:
            await tm.finish_run(
                run_id=tool_run_id,
                output={
                    "match_count": len(result.matches),
                    "latency_ms": result.latency_ms,
                    "status_code": result.status_code,
                },
                status="SUCCESS" if result.error is None else "FAILED",
                error_message=result.error,
            )
        except Exception:
            log.warning("lease_lookup.finish_tool_run.failed", exc_info=True)

    # ── Handle error from service (connection failures, non-200, …) ───────────
    if result.error:
        log.warning(
            "lease_lookup.service_error",
            error=result.error,
            status_code=result.status_code,
        )
        return {
            "status": "WAITING_FOR_USER",
            "response_message": _NO_MATCH_MESSAGE,
            "response_ui": {
                "type": "text_question",
                "field": "lease_code",
                "message": _NO_MATCH_MESSAGE,
            },
        }

    match_count = len(result.matches)
    log.info("lease_lookup.result", match_count=match_count)

    # ── 0 matches: ask for more details ──────────────────────────────────────
    if match_count == 0:
        return {
            "status": "WAITING_FOR_USER",
            "response_message": _NO_MATCH_MESSAGE,
            "response_ui": {
                "type": "text_question",
                "field": "lease_code",
                "message": _NO_MATCH_MESSAGE,
            },
        }

    # ── 1 match: auto-enrich collected_data ───────────────────────────────────
    if match_count == 1:
        record = result.matches[0]
        enriched = _enrich_collected_data(collected, record)
        log.info(
            "lease_lookup.auto_enriched",
            lease_code=record.lease_code,
            brand=record.brand,
            mall=record.mall,
        )
        return {
            "collected_data": enriched,
            "lease_matches": [],
            "status": "IN_PROGRESS",
        }

    # ── N matches: surface selection UI ───────────────────────────────────────
    match_dicts = [m.model_dump() for m in result.matches]
    return {
        "lease_matches": match_dicts,
        "status": "WAITING_FOR_USER",
        "response_message": _MULTI_MATCH_MESSAGE,
        "response_ui": {
            "type": "lease_selection",
            "matches": match_dicts,
            "message": _MULTI_MATCH_MESSAGE,
        },
    }
