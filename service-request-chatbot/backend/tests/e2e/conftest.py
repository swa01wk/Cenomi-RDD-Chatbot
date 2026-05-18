"""E2E test fixtures.

All fixtures target the full FastAPI application stack:
  - httpx.AsyncClient with ASGITransport drives the HTTP layer.
  - _get_db is overridden with an AsyncMock so no real database is needed.
  - LLM, Lease API, and SR API are patched with deterministic stubs.
  - ChatOrchestrationService and the LangGraph graph are NOT patched — they
    run for real so that every routing decision, validation, and observability
    call exercises production code.

Session-scoped patches
----------------------
``mock_llm_gateway``  — replaces the LLMGateway singleton via set_default_gateway.
``mock_lease_api``    — replaces get_lease_lookup_service at the node level.
``mock_sr_api``       — replaces get_service_request_api_service at the node level.

Function-scoped fixtures
------------------------
``app_client``        — fresh ASGI client per test with the DB override active.
``all_fields_data``   — fully-populated collected_data dict helper.
``sample_lease``      — single LeaseRecord helper.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.services.lease_lookup_service import LeaseRecord, LeaseLookupResult
from app.agents.schemas.supervisor_schema import SupervisorDecision

# Expose builders for backward-compat imports in test modules that may import
# from conftest (via sys.path when pytest is run from the backend directory)
from tests.e2e.helpers import (  # noqa: F401 — re-export for convenience
    make_field_extraction_mock,
    make_lease_mock,
    make_sr_api_mock,
    make_supervisor_mock,
    zara_lease,
    all_collected_data,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHAT_ENDPOINT = "/api/chat/service-request"


# ---------------------------------------------------------------------------
# Mock DB session factory
# ---------------------------------------------------------------------------


def _make_mock_db() -> AsyncMock:
    """Build a no-op AsyncSession mock with all hooks wired."""
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
# Lease data helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_lease() -> LeaseRecord:
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


@pytest.fixture()
def all_fields_data(sample_lease: LeaseRecord) -> dict[str, Any]:
    """Fully-populated collected_data satisfying all CREATE_SR required fields."""
    return {
        # Backend-derived
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
        "description": "Formal handover for unit RP-E2E-01",
        "startDate": "2025-05-01",
        "endDate": "2025-06-01",
        "inspection_done_by": "FM_MANAGER",
        "comments": "Ready for handover inspection",
    }


# ---------------------------------------------------------------------------
# Supervisor LLM mock builder
# ---------------------------------------------------------------------------


def _make_supervisor_mock(
    intent: str = "CREATE_HANDOVER_SERVICE_REQUEST",
    confidence: float = 0.92,
    service_category: str | None = "FIT_OUT_AND_HANDOVER",
    sub_category: str | None = "HANDOVER",
    target_agent: str | None = "handover_service_request_agent",
) -> AsyncMock:
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
# Field extraction mock builder
# ---------------------------------------------------------------------------


def _make_field_extraction_mock(fields: dict | None = None) -> MagicMock:
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
# Lease service mock builder
# ---------------------------------------------------------------------------


def _make_lease_mock(records: list[LeaseRecord]) -> MagicMock:
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
# SR API mock builder
# ---------------------------------------------------------------------------


def _make_sr_api_mock(sr_id: str = "SR-E2E-001", *, error: str | None = None) -> MagicMock:
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
# Main app client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client with the DB dependency overridden.

    Yields an ``AsyncClient`` scoped to one test function.  The DB override
    is active for the duration of the test and cleaned up afterwards.
    """
    from app.main import app
    from app.db.session import _get_db

    transport = ASGITransport(app=app)
    mock_db = _make_mock_db()

    def _override_db():
        yield mock_db

    app.dependency_overrides[_get_db] = _override_db

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience: post one chat turn
# ---------------------------------------------------------------------------


async def post_turn(
    client: AsyncClient,
    message: str,
    *,
    session_id: str | None = None,
    user_id: str = "user_e2e_test",
    attachments: list | None = None,
) -> dict[str, Any]:
    """Helper: POST a chat turn and return the response body dict."""
    payload: dict[str, Any] = {
        "user_id": user_id,
        "message": message,
        "attachments": attachments or [],
    }
    if session_id is not None:
        payload["session_id"] = session_id

    resp = await client.post(_CHAT_ENDPOINT, json=payload)
    return resp.json()


# ---------------------------------------------------------------------------
# Expose builders for use in test modules
# ---------------------------------------------------------------------------

make_supervisor_mock = _make_supervisor_mock
make_field_extraction_mock = _make_field_extraction_mock
make_lease_mock = _make_lease_mock
make_sr_api_mock = _make_sr_api_mock
