"""Integration tests for the full service-request LangGraph.

Each test compiles the graph, patches all external I/O (LLM calls, lease API,
SR API), and invokes the graph end-to-end via ``ainvoke``.  Assertions check
the final accumulated state.  No database, no network required.

Test coverage
-------------
test_first_user_message        — new session, supervisor classifies intent
test_lease_code_provided       — single lease match, auto-enrichment
test_multiple_lease_selection  — N lease matches, selection UI shown
test_missing_fields            — lease resolved, user-supplied fields pending
test_validation_error          — blocking validation error, correction asked
test_confirmation              — all fields valid, confirmation card shown
test_submission                — user confirms, payload built and submitted
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.graph.service_request_graph import build_service_request_graph
from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.services.lease_lookup_service import (
    LeaseRecord,
    LeaseLookupResult,
)

# ---------------------------------------------------------------------------
# Graph singleton — compiled once per module to keep test startup fast
# ---------------------------------------------------------------------------

_GRAPH = build_service_request_graph()


# ---------------------------------------------------------------------------
# State / data helpers
# ---------------------------------------------------------------------------


def _base_state(**overrides: object) -> dict:
    """Return a minimal state dict sufficient for any graph invocation."""
    return {
        "session_id": "integ-session-001",
        "user_id": "integ-user-001",
        "user_message": "test message",
        **overrides,
    }


def _all_fields() -> dict:
    """Return a fully-populated ``collected_data`` satisfying all CREATE_SR fields."""
    return {
        # Backend-derived (from lease lookup)
        "tenant_profile_id": 1001,
        "property_id": 2001,
        "lease_code": "LC-2024-001",
        "lease_id": 3001,
        "brand_id": 4001,
        "unit_codes": ["RYP-101"],
        "city": "Riyadh",
        "contracted_area": 350.0,
        # User-supplied
        "mall": "Riyadh Park",
        "brand": "Zara",
        "lease": "Zara @ Riyadh Park 2024",
        "title": "Handover for Zara @ Riyadh Park",
        "description": "Formal handover request for unit RYP-101",
        "startDate": "2024-02-01",
        "endDate": "2024-03-01",
        "inspection_done_by": "FM Team",
        "comments": "Ready for handover",
    }


def _partial_fields() -> dict:
    """Backend fields resolved; user-supplied fields (title, description, dates…) missing."""
    return {
        "tenant_profile_id": 1001,
        "property_id": 2001,
        "lease_code": "LC-2024-001",
        "lease_id": 3001,
        "brand_id": 4001,
        "unit_codes": ["RYP-101"],
        "city": "Riyadh",
        "contracted_area": 350.0,
        "mall": "Riyadh Park",
        "brand": "Zara",
        "lease": "Zara @ Riyadh Park 2024",
        # title, description, startDate, endDate, inspection_done_by, comments — missing
    }


def _sample_lease_record() -> LeaseRecord:
    return LeaseRecord(
        lease_code="LC-2024-001",
        lease_id=3001,
        contract_id=5001,
        brand="Zara",
        brand_id=4001,
        mall="Riyadh Park",
        property_id=2001,
        tenant_profile_id=1001,
        unit_codes=["RYP-101"],
        contracted_area=350.0,
        city="Riyadh",
        lease_brand_mall="Zara@Riyadh Park",
    )


def _lease_result(matches: list[LeaseRecord], *, error: str | None = None) -> LeaseLookupResult:
    return LeaseLookupResult(
        matches=matches,
        endpoint="/api/leases",
        request_payload={},
        response_payload={"results": [m.model_dump() for m in matches]},
        latency_ms=50,
        status_code=200 if not error else 500,
        error=error,
    )


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _mock_field_extraction_class(fields: dict | None = None) -> MagicMock:
    """Return a mock ``FieldExtractionService`` class.

    The instantiated mock's ``extract`` coroutine returns *fields* (or an empty
    dict) wrapped in the shape that ``field_extraction_node`` expects.
    """
    mock_result = MagicMock()
    mock_result.to_state_dict.return_value = fields or {}
    mock_result.summary = ""

    mock_meta = MagicMock()
    mock_meta.parse_success = True
    mock_meta.latency_ms = 100
    mock_meta.retry_count = 0
    mock_meta.input_tokens = 100
    mock_meta.output_tokens = 50
    mock_meta.parse_error = None

    mock_svc = MagicMock()
    mock_svc.extract = AsyncMock(return_value=(mock_result, mock_meta))

    return MagicMock(return_value=mock_svc)


def _mock_lease_factory(matches: list[LeaseRecord], *, error: str | None = None) -> MagicMock:
    """Return a mock ``get_lease_lookup_service`` factory producing *matches*."""
    mock_svc = AsyncMock()
    mock_svc.lookup.return_value = _lease_result(matches, error=error)
    return MagicMock(return_value=mock_svc)


def _mock_supervisor_llm(
    intent: str = "CREATE_HANDOVER_SERVICE_REQUEST",
    confidence: float = 0.9,
    service_category: str | None = "FIT_OUT_AND_HANDOVER",
    sub_category: str | None = "HANDOVER",
    target_agent: str | None = "handover_service_request_agent",
) -> AsyncMock:
    """Return an ``AsyncMock`` for ``_call_supervisor_llm`` yielding a valid decision."""
    decision = SupervisorDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        service_category=service_category,
        sub_category=sub_category,
        target_agent=target_agent,
        reasoning="integration test decision",
    )
    return AsyncMock(return_value=(decision, 100, 50, 200))


def _mock_sr_api_factory(sr_id: str = "SR-2024-001") -> MagicMock:
    """Return a mock ``get_service_request_api_service`` factory."""
    mock_result = MagicMock()
    mock_result.sr_id = sr_id
    mock_result.error = None
    mock_result.status_code = 201
    mock_result.latency_ms = 300
    mock_result.correlation_id = "CORR-001"
    mock_result.endpoint = "/api/service-requests"
    mock_result.response_payload = {"id": sr_id}

    mock_svc = AsyncMock()
    mock_svc.create_service_request.return_value = mock_result
    return MagicMock(return_value=mock_svc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_user_message() -> None:
    """Brand-new session: supervisor classifies intent, pipeline asks for lease.

    Graph path
    ----------
    START → load_session → supervisor → registry → handover_entry →
    field_extraction → merge_state → lease_lookup (no identifiers) →
    response_generation → save_state → END
    """
    with (
        patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            _mock_supervisor_llm(),
        ),
        patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(user_message="I want to create a handover service request")
        )

    # Supervisor + registry set the active agent
    assert result["active_agent"] == "handover_service_request_agent"
    assert result["intent"] == "CREATE_HANDOVER_SERVICE_REQUEST"
    # Lease lookup returns WAITING_FOR_USER because no identifiers were provided
    assert result["status"] == "WAITING_FOR_USER"
    assert result.get("response_message"), "Expected a non-empty response_message"


@pytest.mark.asyncio
async def test_lease_code_provided() -> None:
    """Field extraction finds a lease code; lease API resolves one match.

    Graph path
    ----------
    load_session → handover_entry → field_extraction → merge_state →
    lease_lookup (1 match, auto-enrich) → validation → missing_field →
    response_generation → save_state → END
    """
    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(
                {"lease_code": {"value": "LC-2024-001", "confidence": 0.95}}
            ),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.lease_lookup_node.get_lease_lookup_service",
            _mock_lease_factory([_sample_lease_record()]),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="The lease code is LC-2024-001",
                active_agent="handover_service_request_agent",
                collected_data={},
                workflow_stage="CREATE_SR",
            )
        )

    # Lease was resolved by the single-match auto-enrichment path
    assert result["collected_data"]["lease_id"] == 3001
    assert result["collected_data"]["brand"] == "Zara"
    assert result["collected_data"]["city"] == "Riyadh"
    # User-supplied fields still missing → still waiting
    assert result["status"] == "WAITING_FOR_USER"
    assert result.get("response_message"), "Expected a question about the next missing field"
    assert result.get("missing_fields"), "missing_fields list should be populated"


@pytest.mark.asyncio
async def test_multiple_lease_selection() -> None:
    """Lease API returns multiple matches — frontend receives a selection widget.

    Graph path
    ----------
    ... → merge_state → lease_lookup (N matches, WAITING_FOR_USER) →
    response_generation → save_state → END
    """
    record_a = _sample_lease_record()
    record_b = LeaseRecord(
        lease_code="LC-2024-002",
        lease_id=3002,
        contract_id=5002,
        brand="Zara",
        brand_id=4001,
        mall="Mall of Arabia",
        property_id=2002,
        tenant_profile_id=1001,
        unit_codes=["MOA-201"],
        contracted_area=280.0,
        city="Jeddah",
        lease_brand_mall="Zara@Mall of Arabia",
    )

    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(
                {
                    "brand": {"value": "Zara", "confidence": 0.9},
                    "mall": {"value": "Riyadh", "confidence": 0.7},
                }
            ),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.lease_lookup_node.get_lease_lookup_service",
            _mock_lease_factory([record_a, record_b]),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="Brand Zara",
                active_agent="handover_service_request_agent",
                collected_data={},
                workflow_stage="CREATE_SR",
            )
        )

    assert result["status"] == "WAITING_FOR_USER"
    assert result["response_ui"]["type"] == "lease_selection"
    assert len(result["lease_matches"]) == 2


@pytest.mark.asyncio
async def test_missing_fields() -> None:
    """Lease resolved but user-supplied fields are missing — node asks next question.

    Graph path
    ----------
    ... → merge_state (lease already resolved) → validation → missing_field →
    response_generation → save_state → END
    """
    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(),  # nothing new in user message
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="ok, what next?",
                active_agent="handover_service_request_agent",
                collected_data=_partial_fields(),
                workflow_stage="CREATE_SR",
            )
        )

    assert result["status"] == "WAITING_FOR_USER"
    assert result.get("response_message"), "Expected a clarifying question"
    # missing_field_node writes the list of still-missing fields
    missing = result.get("missing_fields") or []
    assert len(missing) > 0, "Expected missing_fields to be non-empty"
    # None of the user-supplied fields (title, description, etc.) should be present
    assert "title" in missing or "description" in missing


@pytest.mark.asyncio
async def test_validation_error() -> None:
    """All fields present but a blocking validation error stops progression.

    Graph path
    ----------
    ... → validation (blocking error) → missing_field → response_generation →
    save_state → END

    The blocking error is recorded in state; the turn ends with WAITING_FOR_USER
    so the frontend can surface the error to the user.
    """
    blocking_error = {
        "field": "endDate",
        "message": "End date must be after start date.",
        "blocking": True,
    }

    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[blocking_error]),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="continue",
                active_agent="handover_service_request_agent",
                collected_data=_all_fields(),
                workflow_stage="CREATE_SR",
            )
        )

    assert result["status"] == "WAITING_FOR_USER"
    blocking = [e for e in (result.get("validation_errors") or []) if e.get("blocking")]
    assert len(blocking) == 1
    assert blocking[0]["field"] == "endDate"


@pytest.mark.asyncio
async def test_confirmation() -> None:
    """All fields valid — confirmation card is displayed and turn pauses.

    Graph path
    ----------
    ... → validation (clean) → confirmation (build card, status=PENDING) →
    response_generation (status=WAITING_FOR_USER) → save_state → END
    """
    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="continue",
                active_agent="handover_service_request_agent",
                collected_data=_all_fields(),
                workflow_stage="CREATE_SR",
            )
        )

    assert result["confirmation_status"] == "PENDING"
    assert result["confirmation_required"] is True
    assert result["response_ui"]["type"] == "confirmation_card"
    # response_generation resets to WAITING_FOR_USER for all non-terminal statuses
    assert result["status"] == "WAITING_FOR_USER"
    # Card should include key display fields
    card_field_keys = {f["key"] for f in result["response_ui"]["fields"]}
    assert "lease_code" in card_field_keys
    assert "title" in card_field_keys


@pytest.mark.asyncio
async def test_submission() -> None:
    """User confirms → payload built, SR API called, SR ID returned.

    Graph path
    ----------
    START → load_session → handover_entry (YES detected → CONFIRMED) →
    field_extraction → merge_state → validation → confirmation (pass-through) →
    payload_builder → api_submission → response_generation (SUBMITTED) →
    save_state → END

    The turn starts with ``confirmation_status="PENDING"`` (saved from the
    previous turn when the card was shown) and ``user_message="yes"``.
    ``handover_entry_node`` detects the confirmation phrase and sets
    ``confirmation_status="CONFIRMED"``.  ``confirmation_node`` sees CONFIRMED
    and returns ``{}`` — preserving the status.  The graph then proceeds to
    payload building and API submission.
    """
    with (
        patch(
            "app.agents.graph.nodes.field_extraction_node.FieldExtractionService",
            _mock_field_extraction_class(),
        ),
        patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.graph.nodes.validation_node._validation_service.validate_draft",
            MagicMock(return_value=[]),
        ),
        patch(
            "app.agents.graph.nodes.payload_builder_node.build_create_handover_payload",
            MagicMock(
                return_value={
                    "lease_id": 3001,
                    "title": "Handover for Zara @ Riyadh Park",
                    "startDate": "2024-02-01",
                    "endDate": "2024-03-01",
                }
            ),
        ),
        patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            _mock_sr_api_factory("SR-2024-001"),
        ),
    ):
        result = await _GRAPH.ainvoke(
            _base_state(
                user_message="yes",
                active_agent="handover_service_request_agent",
                collected_data=_all_fields(),
                workflow_stage="CREATE_SR",
                confirmation_status="PENDING",  # state saved from prior confirmation turn
            )
        )

    # Submission succeeded
    assert result["status"] == "SUBMITTED"
    assert "SR-2024-001" in result["response_message"]
    assert result["backend_refs"]["sr_id"] == "SR-2024-001"
    assert result["backend_refs"]["service_request_status"] == "SUBMITTED"
    # workflow_stage advances to SR_CREATED on success
    assert result["workflow_stage"] == "SR_CREATED"
