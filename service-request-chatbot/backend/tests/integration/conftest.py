"""Shared fixtures for integration tests.

These fixtures wire up deterministic mocks for all external I/O (LLM, Lease
API, SR API, DB session) so that integration tests can run the full compiled
LangGraph without any network access or database.

Usage
-----
Import these fixtures in any integration test module via normal pytest fixture
injection.  All fixtures are function-scoped by default so state never leaks
between tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.services.lease_lookup_service import (
    LeaseRecord,
    LeaseLookupResult,
)


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db() -> AsyncMock:
    """Async SQLAlchemy session stub — add/flush/execute are all no-ops.

    ``session.execute`` returns a result where:
    - ``scalar_one_or_none()`` → ``None``  (SELECT queries return nothing)
    - ``scalar_one()``         → ``0``     (COUNT queries return 0)
    - ``scalars()``            → empty iterator
    """
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalar_one.return_value = 0
    scalars_mock = MagicMock()
    scalars_mock.__iter__ = MagicMock(return_value=iter([]))
    result_mock.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# LLM gateway
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm_gateway() -> MagicMock:
    """Deterministic LLMGateway stub.

    By default ``complete_json`` returns a CREATE_HANDOVER_SERVICE_REQUEST
    supervisor decision at confidence 0.92.  Individual tests can override
    ``complete_json.return_value`` as needed.
    """
    from app.agents.llm.gateway import LLMGateway

    gateway = MagicMock(spec=LLMGateway)
    gateway.model = "gpt-4o-mini"
    gateway.complete_json = AsyncMock(
        return_value=(
            {
                "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
                "confidence": 0.92,
                "service_category": "FIT_OUT_AND_HANDOVER",
                "sub_category": "HANDOVER",
                "target_agent": "handover_service_request_agent",
                "reasoning": "Integration test: user wants handover SR",
            },
            100,  # input_tokens
            60,   # output_tokens
            150,  # latency_ms
        )
    )
    return gateway


# ---------------------------------------------------------------------------
# Supervisor decision
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_supervisor_decision() -> SupervisorDecision:
    """High-confidence CREATE_HANDOVER_SERVICE_REQUEST decision."""
    return SupervisorDecision(
        intent="CREATE_HANDOVER_SERVICE_REQUEST",
        confidence=0.92,
        service_category="FIT_OUT_AND_HANDOVER",
        sub_category="HANDOVER",
        target_agent="handover_service_request_agent",
        reasoning="Integration test decision",
    )


# ---------------------------------------------------------------------------
# Lease data helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_lease() -> LeaseRecord:
    """A single resolved LeaseRecord used across integration tests."""
    return LeaseRecord(
        lease_code="LC-INTEG-001",
        lease_id=9001,
        contract_id=8001,
        brand="Zara",
        brand_id=88,
        mall="Riyadh Park",
        property_id=2018,
        tenant_profile_id=77,
        unit_codes=["RP-G01"],
        contracted_area=420.0,
        city="Riyadh",
        lease_brand_mall="LC-INTEG-001 - Zara - Riyadh Park",
    )


@pytest.fixture()
def all_fields_data(sample_lease: LeaseRecord) -> dict[str, Any]:
    """Fully-populated ``collected_data`` satisfying all CREATE_SR required fields."""
    return {
        # Backend-derived (lease lookup)
        "tenant_profile_id": sample_lease.tenant_profile_id,
        "property_id": sample_lease.property_id,
        "lease_code": sample_lease.lease_code,
        "lease_id": sample_lease.lease_id,
        "contract_id": sample_lease.contract_id,
        "brand_id": sample_lease.brand_id,
        "unit_codes": sample_lease.unit_codes,
        "city": sample_lease.city,
        "contracted_area": sample_lease.contracted_area,
        "lease_brand_mall": sample_lease.lease_brand_mall,
        # User-supplied
        "mall": sample_lease.mall,
        "brand": sample_lease.brand,
        "title": "Handover for Zara @ Riyadh Park",
        "description": "Formal handover for unit RP-G01",
        "startDate": "2025-03-01",
        "endDate": "2025-04-01",
        "inspection_done_by": "FM_MANAGER",
        "comments": "Ready for handover inspection",
    }


# ---------------------------------------------------------------------------
# Lease service mock factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_lease_service(sample_lease: LeaseRecord) -> MagicMock:
    """``get_lease_lookup_service`` factory returning a single-match result."""
    svc = AsyncMock()
    svc.lookup = AsyncMock(
        return_value=LeaseLookupResult(
            matches=[sample_lease],
            endpoint="mock://lease-api/leases",
            request_payload={},
            response_payload={"leases": [sample_lease.model_dump()]},
            latency_ms=30,
            status_code=200,
        )
    )
    return MagicMock(return_value=svc)


@pytest.fixture()
def mock_multi_lease_service(sample_lease: LeaseRecord) -> MagicMock:
    """``get_lease_lookup_service`` factory returning two lease matches."""
    lease_b = LeaseRecord(
        lease_code="LC-INTEG-002",
        lease_id=9002,
        contract_id=8002,
        brand="Zara",
        brand_id=88,
        mall="Mall of Arabia",
        property_id=1905,
        tenant_profile_id=77,
        unit_codes=["MOA-201"],
        contracted_area=350.0,
        city="Jeddah",
        lease_brand_mall="LC-INTEG-002 - Zara - Mall of Arabia",
    )
    svc = AsyncMock()
    svc.lookup = AsyncMock(
        return_value=LeaseLookupResult(
            matches=[sample_lease, lease_b],
            endpoint="mock://lease-api/leases",
            request_payload={},
            response_payload={"leases": [sample_lease.model_dump(), lease_b.model_dump()]},
            latency_ms=30,
            status_code=200,
        )
    )
    return MagicMock(return_value=svc)


@pytest.fixture()
def mock_no_lease_service() -> MagicMock:
    """``get_lease_lookup_service`` factory returning zero matches."""
    svc = AsyncMock()
    svc.lookup = AsyncMock(
        return_value=LeaseLookupResult(
            matches=[],
            endpoint="mock://lease-api/leases",
            request_payload={},
            response_payload={"leases": []},
            latency_ms=20,
            status_code=200,
        )
    )
    return MagicMock(return_value=svc)


# ---------------------------------------------------------------------------
# SR API service mock factory
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sr_api_service() -> MagicMock:
    """``get_service_request_api_service`` factory — successful creation."""
    result = MagicMock()
    result.sr_id = "SR-INTEG-001"
    result.error = None
    result.status_code = 201
    result.latency_ms = 250
    result.correlation_id = "CORR-INTEG-001"
    result.endpoint = "/api/service-requests"
    result.response_payload = {"id": "SR-INTEG-001"}

    svc = AsyncMock()
    svc.create_service_request = AsyncMock(return_value=result)
    return MagicMock(return_value=svc)


@pytest.fixture()
def mock_sr_api_failure() -> MagicMock:
    """``get_service_request_api_service`` factory — API returns an error."""
    result = MagicMock()
    result.sr_id = None
    result.error = "Internal Server Error"
    result.status_code = 500
    result.latency_ms = 100
    result.correlation_id = None
    result.endpoint = "/api/service-requests"
    result.response_payload = {"error": "Internal Server Error"}

    svc = AsyncMock()
    svc.create_service_request = AsyncMock(return_value=result)
    return MagicMock(return_value=svc)
