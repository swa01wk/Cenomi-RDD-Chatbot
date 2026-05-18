"""Unit tests — lease_lookup_node.

Test groups
-----------
TestNoIdentifiers           — No lease-identifying fields → ask for lease_code.
TestSelectedLeaseMerge      — selected_lease present → merged into collected_data.
TestSelectedLeaseInvalid    — Malformed selected_lease → graceful error response.
TestZeroMatches             — Service returns 0 matches → ask for more details.
TestSingleMatch             — Service returns 1 match → collected_data enriched.
TestMultipleMatches         — Service returns N matches → lease_selection UI.
TestBackendFieldProtection  — Backend-derived fields come only from lookup result.
TestTracing                 — capture_tool_call called with correct arguments.
TestServiceError            — HTTP / connection error from service → WAITING_FOR_USER.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.agents.graph.nodes.lease_lookup_node import (
    _LEASE_ENRICHMENT_FIELDS,
    _MULTI_MATCH_MESSAGE,
    _NO_LEASE_FIELDS_MESSAGE,
    _NO_MATCH_MESSAGE,
    lease_lookup_node,
)
from app.agents.graph.nodes.merge_state_node import BACKEND_PROTECTED_FIELDS
from app.agents.services.lease_lookup_service import (
    AbstractLeaseLookupService,
    LeaseRecord,
    LeaseLookupQuery,
    LeaseLookupResult,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_UA_RECORD = LeaseRecord(
    lease_code="t0105712",
    lease_id=95404,
    contract_id=95404,
    brand="Brand Under Armour",
    brand_id=267,
    mall="Jawharat Jeddah",
    property_id=3041,
    tenant_profile_id=116,
    unit_codes=["FF050"],
    contracted_area=420.0,
    city="Jeddah",
    lease_brand_mall="t0105712 - Brand Under Armour - Jawharat Jeddah",
)

_NIKE_RYD = LeaseRecord(
    lease_code="t0208831",
    lease_id=88210,
    contract_id=88210,
    brand="Nike",
    brand_id=312,
    mall="Riyadh Park",
    property_id=2018,
    tenant_profile_id=204,
    unit_codes=["GF101"],
    contracted_area=680.0,
    city="Riyadh",
    lease_brand_mall="t0208831 - Nike - Riyadh Park",
)

_NIKE_MOA = LeaseRecord(
    lease_code="t0301144",
    lease_id=71033,
    contract_id=71033,
    brand="Nike",
    brand_id=312,
    mall="Mall of Arabia",
    property_id=1905,
    tenant_profile_id=204,
    unit_codes=["LG220"],
    contracted_area=510.0,
    city="Jeddah",
    lease_brand_mall="t0301144 - Nike - Mall of Arabia",
)


def _make_result(
    matches: list[LeaseRecord],
    error: str | None = None,
    status_code: int | None = 200,
    latency_ms: int = 15,
) -> LeaseLookupResult:
    return LeaseLookupResult(
        matches=matches,
        endpoint="mock://lease-tenant-api/leases",
        request_payload={"endpoint": "mock://lease-tenant-api/leases"},
        response_payload={"leases": [m.model_dump() for m in matches]},
        latency_ms=latency_ms,
        status_code=status_code,
        error=error,
    )


class _MockService(AbstractLeaseLookupService):
    """Test double — configurable match list."""

    def __init__(self, result: LeaseLookupResult) -> None:
        self._result = result

    async def lookup(self, query: LeaseLookupQuery) -> LeaseLookupResult:
        return self._result


def _state(**overrides: Any) -> dict[str, Any]:
    return {"session_id": "sess-test", "user_id": "user-test", **overrides}


def _make_trace_manager() -> MagicMock:
    tm = MagicMock()
    tm.start_run = AsyncMock(return_value=uuid4())
    tm.finish_run = AsyncMock()
    tm.capture_tool_call = AsyncMock()
    tm.capture_state_snapshot = AsyncMock()
    tm.capture_state_diff = AsyncMock()
    return tm


# ---------------------------------------------------------------------------
# TestNoIdentifiers
# ---------------------------------------------------------------------------


class TestNoIdentifiers:
    @pytest.mark.asyncio
    async def test_no_identifiers_returns_waiting(self) -> None:
        state = _state(collected_data={})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_no_identifiers_asks_for_lease_code(self) -> None:
        state = _state(collected_data={})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["response_ui"]["field"] == "lease_code"

    @pytest.mark.asyncio
    async def test_no_identifiers_response_ui_type_is_text_question(self) -> None:
        state = _state(collected_data={})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["response_ui"]["type"] == "text_question"

    @pytest.mark.asyncio
    async def test_no_identifiers_response_message_non_empty(self) -> None:
        state = _state(collected_data={})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result.get("response_message")

    @pytest.mark.asyncio
    async def test_no_identifiers_service_not_called(self) -> None:
        """Service.lookup should NOT be called when there are no identifiers."""
        state = _state(collected_data={})
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        await lease_lookup_node(state, service=svc)
        svc.lookup.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_collected_data_key_treats_as_no_identifiers(self) -> None:
        state = _state()  # no collected_data key at all
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"


# ---------------------------------------------------------------------------
# TestSelectedLeaseMerge
# ---------------------------------------------------------------------------


class TestSelectedLeaseMerge:
    @pytest.mark.asyncio
    async def test_selected_lease_merged_into_collected_data(self) -> None:
        state = _state(
            collected_data={"title": "My Handover"},
            selected_lease=_UA_RECORD.model_dump(),
            lease_matches=[_UA_RECORD.model_dump()],
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        assert cd["lease_code"] == "t0105712"
        assert cd["brand"] == "Brand Under Armour"
        assert cd["mall"] == "Jawharat Jeddah"
        assert cd["city"] == "Jeddah"
        assert cd["tenant_profile_id"] == 116
        assert cd["property_id"] == 3041

    @pytest.mark.asyncio
    async def test_selected_lease_preserves_existing_user_fields(self) -> None:
        state = _state(
            collected_data={"title": "My Handover", "description": "Test"},
            selected_lease=_UA_RECORD.model_dump(),
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        assert cd["title"] == "My Handover"
        assert cd["description"] == "Test"

    @pytest.mark.asyncio
    async def test_selected_lease_sets_status_in_progress(self) -> None:
        state = _state(
            collected_data={},
            selected_lease=_UA_RECORD.model_dump(),
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_selected_lease_clears_lease_matches(self) -> None:
        state = _state(
            collected_data={},
            selected_lease=_UA_RECORD.model_dump(),
            lease_matches=[_UA_RECORD.model_dump()],
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        assert result["lease_matches"] == []

    @pytest.mark.asyncio
    async def test_selected_lease_clears_selected_lease(self) -> None:
        state = _state(
            collected_data={},
            selected_lease=_UA_RECORD.model_dump(),
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        assert result["selected_lease"] is None

    @pytest.mark.asyncio
    async def test_selected_lease_does_not_call_service(self) -> None:
        state = _state(
            collected_data={},
            selected_lease=_UA_RECORD.model_dump(),
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        await lease_lookup_node(state, service=svc)
        svc.lookup.assert_not_called()

    @pytest.mark.asyncio
    async def test_selected_lease_all_enrichment_fields_present(self) -> None:
        state = _state(
            collected_data={},
            selected_lease=_UA_RECORD.model_dump(),
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        for field_name in _LEASE_ENRICHMENT_FIELDS:
            assert field_name in cd, f"Expected '{field_name}' in collected_data"


# ---------------------------------------------------------------------------
# TestSelectedLeaseInvalid
# ---------------------------------------------------------------------------


class TestSelectedLeaseInvalid:
    @pytest.mark.asyncio
    async def test_malformed_selected_lease_returns_waiting(self) -> None:
        state = _state(
            collected_data={},
            selected_lease={"not_a_valid": "record"},
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_malformed_selected_lease_has_response_ui(self) -> None:
        state = _state(
            collected_data={},
            selected_lease={"bad": "data"},
        )
        svc = MagicMock(spec=AbstractLeaseLookupService)
        svc.lookup = AsyncMock()
        result = await lease_lookup_node(state, service=svc)
        assert "response_ui" in result


# ---------------------------------------------------------------------------
# TestZeroMatches
# ---------------------------------------------------------------------------


class TestZeroMatches:
    @pytest.mark.asyncio
    async def test_zero_matches_status_waiting(self) -> None:
        state = _state(collected_data={"lease_code": "UNKNOWN-001"})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_zero_matches_response_ui_type_text_question(self) -> None:
        state = _state(collected_data={"lease_code": "UNKNOWN-001"})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["response_ui"]["type"] == "text_question"

    @pytest.mark.asyncio
    async def test_zero_matches_response_message_non_empty(self) -> None:
        state = _state(collected_data={"lease_code": "UNKNOWN-001"})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result.get("response_message")

    @pytest.mark.asyncio
    async def test_zero_matches_collected_data_unchanged(self) -> None:
        state = _state(collected_data={"lease_code": "UNKNOWN-001", "title": "Test"})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        # collected_data not included in state update (or unchanged)
        assert result.get("collected_data") is None or result["collected_data"].get("title") == "Test"

    @pytest.mark.asyncio
    async def test_zero_matches_by_brand_asks_more(self) -> None:
        state = _state(collected_data={"brand": "UnknownBrand"})
        svc = _MockService(_make_result([]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"


# ---------------------------------------------------------------------------
# TestSingleMatch
# ---------------------------------------------------------------------------


class TestSingleMatch:
    @pytest.mark.asyncio
    async def test_single_match_status_in_progress(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_single_match_enriches_collected_data(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        assert cd["brand"] == "Brand Under Armour"
        assert cd["mall"] == "Jawharat Jeddah"
        assert cd["city"] == "Jeddah"

    @pytest.mark.asyncio
    async def test_single_match_all_backend_fields_populated(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        for field_name in BACKEND_PROTECTED_FIELDS:
            assert field_name in cd, f"Backend field '{field_name}' missing from collected_data"

    @pytest.mark.asyncio
    async def test_single_match_preserves_user_fields(self) -> None:
        state = _state(
            collected_data={"lease_code": "t0105712", "title": "Handover Request"}
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert result["collected_data"]["title"] == "Handover Request"

    @pytest.mark.asyncio
    async def test_single_match_clears_lease_matches(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert result.get("lease_matches") == []

    @pytest.mark.asyncio
    async def test_single_match_no_response_ui_or_waiting(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert "type" not in result.get("response_ui", {}) or result["status"] != "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_single_match_unit_codes_is_list(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert isinstance(result["collected_data"]["unit_codes"], list)


# ---------------------------------------------------------------------------
# TestMultipleMatches
# ---------------------------------------------------------------------------


class TestMultipleMatches:
    @pytest.mark.asyncio
    async def test_multi_match_status_waiting(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_multi_match_response_ui_type_lease_selection(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        assert result["response_ui"]["type"] == "lease_selection"

    @pytest.mark.asyncio
    async def test_multi_match_lease_matches_set(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        assert len(result["lease_matches"]) == 2

    @pytest.mark.asyncio
    async def test_multi_match_response_ui_contains_matches(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        assert len(result["response_ui"]["matches"]) == 2

    @pytest.mark.asyncio
    async def test_multi_match_response_message_non_empty(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        assert result.get("response_message")

    @pytest.mark.asyncio
    async def test_multi_match_collected_data_not_updated(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        # No auto-enrichment on multi-match
        cd = result.get("collected_data")
        assert cd is None or "lease_id" not in cd

    @pytest.mark.asyncio
    async def test_multi_match_lease_matches_are_dicts(self) -> None:
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA]))
        result = await lease_lookup_node(state, service=svc)
        for match in result["lease_matches"]:
            assert isinstance(match, dict)
            assert "lease_code" in match

    @pytest.mark.asyncio
    async def test_three_matches_all_surfaced(self) -> None:
        third = LeaseRecord(
            lease_code="t0999999",
            lease_id=1,
            contract_id=1,
            brand="Nike",
            brand_id=312,
            mall="Another Mall",
            property_id=1,
            tenant_profile_id=1,
            unit_codes=["A01"],
            contracted_area=200.0,
            city="Dubai",
            lease_brand_mall="t0999999 - Nike - Another Mall",
        )
        state = _state(collected_data={"brand": "Nike"})
        svc = _MockService(_make_result([_NIKE_RYD, _NIKE_MOA, third]))
        result = await lease_lookup_node(state, service=svc)
        assert len(result["lease_matches"]) == 3


# ---------------------------------------------------------------------------
# TestBackendFieldProtection
# ---------------------------------------------------------------------------


class TestBackendFieldProtection:
    @pytest.mark.asyncio
    async def test_llm_extracted_backend_fields_not_in_collected_data_before_lookup(
        self,
    ) -> None:
        """Before lookup, extracted_fields must not populate backend-protected keys."""
        # Simulate a state where LLM extraction incorrectly proposed backend IDs.
        state = _state(
            collected_data={"lease_code": "t0105712"},
            extracted_fields={
                "tenant_profile_id": {"value": 9999, "confidence": 0.9},
                "property_id": {"value": 8888, "confidence": 0.9},
            },
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        # Must come from the lookup result (116, 3041), not from extracted_fields (9999, 8888)
        assert cd["tenant_profile_id"] == 116
        assert cd["property_id"] == 3041

    @pytest.mark.asyncio
    async def test_backend_fields_set_from_lookup_result(self) -> None:
        state = _state(collected_data={"lease_code": "t0208831"})
        svc = _MockService(_make_result([_NIKE_RYD]))
        result = await lease_lookup_node(state, service=svc)
        cd = result["collected_data"]
        assert cd["brand_id"] == 312
        assert cd["property_id"] == 2018
        assert cd["unit_codes"] == ["GF101"]
        assert cd["contracted_area"] == 680.0

    @pytest.mark.asyncio
    async def test_lease_enrichment_fields_covers_all_backend_protected(self) -> None:
        """Every BACKEND_PROTECTED_FIELD must also be in _LEASE_ENRICHMENT_FIELDS."""
        for field_name in BACKEND_PROTECTED_FIELDS:
            assert field_name in _LEASE_ENRICHMENT_FIELDS, (
                f"'{field_name}' is in BACKEND_PROTECTED_FIELDS but not in "
                f"_LEASE_ENRICHMENT_FIELDS — node won't populate it from lookup."
            )


# ---------------------------------------------------------------------------
# TestTracing
# ---------------------------------------------------------------------------


class TestTracing:
    @pytest.mark.asyncio
    async def test_capture_tool_call_invoked(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        tm.capture_tool_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_capture_tool_call_tool_name_is_lease_tenant_api(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("tool_name") == "lease_tenant_api"

    @pytest.mark.asyncio
    async def test_capture_tool_call_tool_type_is_http(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("tool_type") == "HTTP"

    @pytest.mark.asyncio
    async def test_capture_tool_call_latency_populated(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD], latency_ms=42))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("latency_ms") == 42

    @pytest.mark.asyncio
    async def test_capture_tool_call_status_code_populated(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD], status_code=200))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("status_code") == 200

    @pytest.mark.asyncio
    async def test_capture_tool_call_success_true_on_no_error(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("success") is True

    @pytest.mark.asyncio
    async def test_capture_tool_call_success_false_on_error(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([], error="HTTP 500", status_code=500))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        assert kwargs.get("success") is False

    @pytest.mark.asyncio
    async def test_finish_run_called_after_tool_call(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        tm.finish_run.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_run_called_with_tool_type(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        # start_run is called at least once — once by the @trace_node decorator, once by the node itself.
        assert tm.start_run.await_count >= 1
        # The node's own child run uses "TOOL" type.
        call_kwargs = [c.kwargs for c in tm.start_run.call_args_list]
        tool_calls = [k for k in call_kwargs if k.get("run_type") == "TOOL"]
        assert len(tool_calls) == 1

    @pytest.mark.asyncio
    async def test_no_trace_manager_does_not_raise(self) -> None:
        """Node must work normally even without a TraceManager in state."""
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([_UA_RECORD]))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_capture_tool_call_request_payload_has_endpoint(self) -> None:
        tm = _make_trace_manager()
        trace_id = uuid4()
        state = _state(
            collected_data={"lease_code": "t0105712"},
            trace_manager=tm,
            trace_id=str(trace_id),
        )
        svc = _MockService(_make_result([_UA_RECORD]))
        await lease_lookup_node(state, service=svc)
        _, kwargs = tm.capture_tool_call.call_args
        req = kwargs.get("request_payload") or {}
        assert "endpoint" in req


# ---------------------------------------------------------------------------
# TestServiceError
# ---------------------------------------------------------------------------


class TestServiceError:
    @pytest.mark.asyncio
    async def test_service_error_returns_waiting(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([], error="HTTP 500", status_code=500))
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_connection_error_returns_waiting(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(
            _make_result([], error="ConnectError: connection refused", status_code=None)
        )
        result = await lease_lookup_node(state, service=svc)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_service_error_response_ui_type_text_question(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712"})
        svc = _MockService(_make_result([], error="HTTP 500", status_code=500))
        result = await lease_lookup_node(state, service=svc)
        assert result["response_ui"]["type"] == "text_question"

    @pytest.mark.asyncio
    async def test_service_error_does_not_corrupt_collected_data(self) -> None:
        state = _state(collected_data={"lease_code": "t0105712", "title": "Test"})
        svc = _MockService(_make_result([], error="HTTP 500", status_code=500))
        result = await lease_lookup_node(state, service=svc)
        cd = result.get("collected_data")
        assert cd is None or cd.get("lease_id") is None
