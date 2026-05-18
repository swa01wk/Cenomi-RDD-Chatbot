"""Reusable mock builders and data helpers for E2E tests.

These are plain functions (not pytest fixtures) that can be imported and
called directly within test functions to set up deterministic mocks for
LLM, Lease API, and SR API.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.services.lease_lookup_service import LeaseRecord, LeaseLookupResult


# ---------------------------------------------------------------------------
# Supervisor LLM mock
# ---------------------------------------------------------------------------


def make_supervisor_mock(
    intent: str = "CREATE_HANDOVER_SERVICE_REQUEST",
    confidence: float = 0.92,
    service_category: str | None = "FIT_OUT_AND_HANDOVER",
    sub_category: str | None = "HANDOVER",
    target_agent: str | None = "handover_service_request_agent",
) -> AsyncMock:
    """Return an AsyncMock for ``_call_supervisor_llm`` with a deterministic decision."""
    decision = SupervisorDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        service_category=service_category,
        sub_category=sub_category,
        target_agent=target_agent,
        reasoning="E2E test decision",
    )
    return AsyncMock(return_value=(decision, 100, 60, 150))


# ---------------------------------------------------------------------------
# Field extraction mock
# ---------------------------------------------------------------------------


def make_field_extraction_mock(fields: dict | None = None) -> MagicMock:
    """Return a MagicMock for ``FieldExtractionService`` with deterministic fields."""
    result = MagicMock()
    result.to_state_dict.return_value = fields or {}
    result.summary = "E2E extraction"

    meta = MagicMock()
    meta.parse_success = True
    meta.latency_ms = 80
    meta.retry_count = 0
    meta.input_tokens = 50
    meta.output_tokens = 30
    meta.parse_error = None

    svc = MagicMock()
    svc.extract = AsyncMock(return_value=(result, meta))
    return MagicMock(return_value=svc)


# ---------------------------------------------------------------------------
# Lease service mock
# ---------------------------------------------------------------------------


def make_lease_mock(records: list[LeaseRecord]) -> MagicMock:
    """Return a MagicMock for ``get_lease_lookup_service`` with *records* as matches."""
    svc = AsyncMock()
    svc.lookup = AsyncMock(
        return_value=LeaseLookupResult(
            matches=records,
            endpoint="mock://lease-api/leases",
            request_payload={},
            response_payload={"leases": [r.model_dump() for r in records]},
            latency_ms=25,
            status_code=200,
        )
    )
    return MagicMock(return_value=svc)


# ---------------------------------------------------------------------------
# SR API mock
# ---------------------------------------------------------------------------


def make_sr_api_mock(sr_id: str = "SR-E2E-001", *, error: str | None = None) -> MagicMock:
    """Return a MagicMock for ``get_service_request_api_service``.

    Pass ``error=<message>`` to simulate an API failure.
    """
    result = MagicMock()
    result.sr_id = sr_id if error is None else None
    result.error = error
    result.status_code = 201 if error is None else 500
    result.latency_ms = 200
    result.correlation_id = "CORR-E2E-001" if error is None else None
    result.endpoint = "/api/service-requests"
    result.response_payload = {"id": sr_id} if error is None else {"error": error}

    svc = AsyncMock()
    svc.create_service_request = AsyncMock(return_value=result)
    return MagicMock(return_value=svc)


# ---------------------------------------------------------------------------
# Lease data helpers
# ---------------------------------------------------------------------------


def zara_lease() -> LeaseRecord:
    """Return a canonical Zara lease for E2E tests."""
    return LeaseRecord(
        lease_code="LC-E2E-001",
        lease_id=7001,
        contract_id=6001,
        brand="Zara",
        brand_id=88,
        mall="Riyadh Park",
        property_id=2018,
        tenant_profile_id=77,
        unit_codes=["RP-E2E-01"],
        contracted_area=420.0,
        city="Riyadh",
        lease_brand_mall="LC-E2E-001 - Zara - Riyadh Park",
    )


def all_collected_data() -> dict[str, Any]:
    """Fully-populated collected_data satisfying all CREATE_SR required fields."""
    lease = zara_lease()
    return {
        "tenant_profile_id": lease.tenant_profile_id,
        "property_id": lease.property_id,
        "lease_code": lease.lease_code,
        "lease_id": lease.lease_id,
        "contract_id": lease.contract_id,
        "brand_id": lease.brand_id,
        "unit_codes": lease.unit_codes,
        "city": lease.city,
        "contracted_area": lease.contracted_area,
        "lease_brand_mall": lease.lease_brand_mall,
        "mall": lease.mall,
        "brand": lease.brand,
        "title": "Handover for Zara @ Riyadh Park",
        "description": "Formal handover for unit RP-E2E-01",
        "startDate": "2025-05-01",
        "endDate": "2025-06-01",
        "inspection_done_by": "FM_MANAGER",
        "comments": "Ready for handover",
    }
