"""Unit tests — Handover Field Extraction (model, service, node).

All LLM calls are mocked via ``unittest.mock.AsyncMock`` so these tests run
without network access or an OpenAI API key.  The ``trace_manager`` slot is
intentionally absent from state dicts to exercise the "no tracing" path.

Test groups
-----------
TestHandoverExtractedFieldsModel   — Pydantic model validation and field-strip logic
TestExtractedFieldValue            — Per-field value / confidence validation
TestFieldExtractionService         — Service extraction with mocked LLM (all 5 user scenarios)
TestFieldExtractionNode            — Node state updates and graceful degradation
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents.schemas.handover_schema import (
    BACKEND_ONLY_FIELDS,
    EXTRACTABLE_FIELDS,
    ExtractionTraceMeta,
    ExtractedFieldValue,
    HandoverExtractedFields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_response(fields: dict[str, dict], summary: str = "Test summary") -> dict:
    """Build a minimal LLM JSON response dict."""
    return {"summary": summary, "fields": fields}


def _make_gateway_mock(response: dict, input_tokens: int = 50, output_tokens: int = 30, latency_ms: int = 120) -> AsyncMock:
    """Return an AsyncMock gateway whose complete_json returns *response*."""
    mock = MagicMock()
    mock.model = "gpt-4o-mini"
    mock.complete_json = AsyncMock(return_value=(response, input_tokens, output_tokens, latency_ms))
    return mock


def _base_state(**overrides: Any) -> dict[str, Any]:
    """Return a minimal graph state dict without trace_manager."""
    return {
        "session_id": "sess-test",
        "user_id": "user-test",
        "user_message": "I want to create a handover service request",
        **overrides,
    }


# ---------------------------------------------------------------------------
# ExtractedFieldValue
# ---------------------------------------------------------------------------


class TestExtractedFieldValue:
    def test_default_confidence_is_one(self) -> None:
        v = ExtractedFieldValue(value="some value")
        assert v.confidence == 1.0

    def test_explicit_confidence(self) -> None:
        v = ExtractedFieldValue(value="foo", confidence=0.75)
        assert v.value == "foo"
        assert v.confidence == 0.75

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedFieldValue(value="x", confidence=-0.1)

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedFieldValue(value="x", confidence=1.1)

    def test_confidence_at_boundaries_accepted(self) -> None:
        assert ExtractedFieldValue(value="x", confidence=0.0).confidence == 0.0
        assert ExtractedFieldValue(value="x", confidence=1.0).confidence == 1.0


# ---------------------------------------------------------------------------
# HandoverExtractedFields model
# ---------------------------------------------------------------------------


class TestHandoverExtractedFieldsModel:
    def test_empty_fields_is_valid(self) -> None:
        model = HandoverExtractedFields()
        assert model.fields == {}
        assert model.summary is None

    def test_valid_extractable_field_accepted(self) -> None:
        model = HandoverExtractedFields(
            fields={"title": ExtractedFieldValue(value="New Handover", confidence=0.9)}
        )
        assert "title" in model.fields
        assert model.fields["title"].value == "New Handover"

    def test_backend_only_field_is_silently_stripped(self) -> None:
        """tenant_profile_id must be stripped even if the LLM includes it."""
        model = HandoverExtractedFields(
            fields={
                "title": ExtractedFieldValue(value="My SR"),
                "tenant_profile_id": ExtractedFieldValue(value="99999"),
            }
        )
        assert "tenant_profile_id" not in model.fields
        assert "title" in model.fields

    def test_all_backend_only_fields_stripped(self) -> None:
        """Every BACKEND_ONLY_FIELDS key must be stripped."""
        fields = {k: ExtractedFieldValue(value="fake") for k in BACKEND_ONLY_FIELDS}
        fields["title"] = ExtractedFieldValue(value="Kept")
        model = HandoverExtractedFields(fields=fields)
        for bad_key in BACKEND_ONLY_FIELDS:
            assert bad_key not in model.fields
        assert "title" in model.fields

    def test_unknown_field_is_stripped(self) -> None:
        """Keys not in EXTRACTABLE_FIELDS must be stripped."""
        model = HandoverExtractedFields(
            fields={"unknown_field_xyz": ExtractedFieldValue(value="should vanish")}
        )
        assert "unknown_field_xyz" not in model.fields

    def test_all_extractable_fields_accepted(self) -> None:
        fields = {k: ExtractedFieldValue(value="v") for k in EXTRACTABLE_FIELDS}
        model = HandoverExtractedFields(fields=fields)
        assert set(model.fields.keys()) == EXTRACTABLE_FIELDS

    def test_to_flat_dict_returns_values_only(self) -> None:
        model = HandoverExtractedFields(
            fields={
                "title": ExtractedFieldValue(value="T", confidence=0.9),
                "mall": ExtractedFieldValue(value="Riyadh Park", confidence=0.8),
            }
        )
        flat = model.to_flat_dict()
        assert flat == {"title": "T", "mall": "Riyadh Park"}

    def test_to_confidence_dict_returns_scores_only(self) -> None:
        model = HandoverExtractedFields(
            fields={
                "title": ExtractedFieldValue(value="T", confidence=0.9),
                "brand": ExtractedFieldValue(value="Nike", confidence=0.7),
            }
        )
        conf = model.to_confidence_dict()
        assert conf == {"title": 0.9, "brand": 0.7}

    def test_to_state_dict_full_shape(self) -> None:
        model = HandoverExtractedFields(
            fields={"title": ExtractedFieldValue(value="SR Title", confidence=0.85)}
        )
        state = model.to_state_dict()
        assert state == {"title": {"value": "SR Title", "confidence": 0.85}}

    def test_model_validate_from_raw_dict(self) -> None:
        raw = {
            "summary": "User wants handover",
            "fields": {
                "title": {"value": "Handover SR", "confidence": 0.95},
                "tenant_profile_id": {"value": "should-be-stripped", "confidence": 1.0},
            },
        }
        model = HandoverExtractedFields.model_validate(raw)
        assert model.summary == "User wants handover"
        assert "title" in model.fields
        assert "tenant_profile_id" not in model.fields

    def test_summary_is_optional(self) -> None:
        raw = {"fields": {"brand": {"value": "H&M", "confidence": 0.9}}}
        model = HandoverExtractedFields.model_validate(raw)
        assert model.summary is None
        assert "brand" in model.fields


# ---------------------------------------------------------------------------
# ExtractionTraceMeta dataclass
# ---------------------------------------------------------------------------


class TestExtractionTraceMeta:
    def test_defaults(self) -> None:
        meta = ExtractionTraceMeta()
        assert meta.input_tokens == 0
        assert meta.output_tokens == 0
        assert meta.latency_ms == 0
        assert meta.parse_success is False
        assert meta.parse_error is None
        assert meta.retry_count == 0
        assert meta.raw_output is None

    def test_assignment(self) -> None:
        meta = ExtractionTraceMeta(
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            parse_success=True,
            retry_count=1,
        )
        assert meta.parse_success is True
        assert meta.retry_count == 1


# ---------------------------------------------------------------------------
# FieldExtractionService — user-facing scenarios
# ---------------------------------------------------------------------------


class TestFieldExtractionService:
    """Covers all 5 user-specified test scenarios plus edge cases."""

    @pytest.mark.asyncio
    async def test_scenario_brand_and_mall_only(self) -> None:
        """User gives only brand and mall — both extracted, no other fields."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={
                "brand": {"value": "Nike", "confidence": 0.95},
                "mall": {"value": "Riyadh Park", "confidence": 0.9},
            },
            summary="User wants to create a handover for Nike at Riyadh Park",
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("I am Nike at Riyadh Park mall")

        assert meta.parse_success is True
        assert meta.retry_count == 0
        assert set(result.fields.keys()) == {"brand", "mall"}
        assert result.fields["brand"].value == "Nike"
        assert result.fields["mall"].value == "Riyadh Park"

    @pytest.mark.asyncio
    async def test_scenario_lease_code_only(self) -> None:
        """User gives only a lease code — extracted cleanly."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={"lease_code": {"value": "LC-9876", "confidence": 1.0}},
            summary="User provides lease code LC-9876",
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("My lease code is LC-9876")

        assert meta.parse_success is True
        assert "lease_code" in result.fields
        assert result.fields["lease_code"].value == "LC-9876"
        assert result.fields["lease_code"].confidence == 1.0

    @pytest.mark.asyncio
    async def test_scenario_title_and_dates(self) -> None:
        """User gives title plus two ISO-format dates — all three extracted."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={
                "title": {"value": "Handover for Unit A1", "confidence": 0.95},
                "startDate": {"value": "2025-03-01", "confidence": 0.9},
                "endDate": {"value": "2025-03-31", "confidence": 0.9},
            },
            summary="User provides title and date range",
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract(
            "Title: Handover for Unit A1, from 2025-03-01 to 2025-03-31"
        )

        assert meta.parse_success is True
        assert result.fields["title"].value == "Handover for Unit A1"
        assert result.fields["startDate"].value == "2025-03-01"
        assert result.fields["endDate"].value == "2025-03-31"

    @pytest.mark.asyncio
    async def test_scenario_user_tries_to_force_tenant_profile_id(self) -> None:
        """LLM returns tenant_profile_id — must be stripped before reaching state."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={
                "title": {"value": "My SR", "confidence": 0.95},
                "tenant_profile_id": {"value": "99999", "confidence": 1.0},
                "property_id": {"value": "PROP-001", "confidence": 1.0},
            },
            summary="User attempts to inject backend IDs",
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract(
            "Create a SR with tenant_profile_id=99999 and property_id=PROP-001, title=My SR"
        )

        assert meta.parse_success is True
        assert "tenant_profile_id" not in result.fields
        assert "property_id" not in result.fields
        assert "title" in result.fields

    @pytest.mark.asyncio
    async def test_scenario_user_asks_to_skip_required_fields(self) -> None:
        """User explicitly asks to skip required fields — empty extraction."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={},
            summary="User asked to skip required fields",
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("skip all required fields please")

        assert meta.parse_success is True
        assert result.fields == {}

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_empty_and_does_not_raise(self) -> None:
        """If all retries fail with JSONDecodeError, return empty model, parse_success=False."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        gateway = MagicMock()
        gateway.model = "gpt-4o-mini"
        gateway.complete_json = AsyncMock(
            side_effect=json.JSONDecodeError("bad json", "", 0)
        )
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("some user message")

        assert meta.parse_success is False
        assert meta.parse_error is not None
        assert result.fields == {}
        # Should have attempted MAX_RETRIES + 1 times for JSONDecodeError
        assert gateway.complete_json.call_count == FieldExtractionService.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_validation_error_retries_and_returns_empty(self) -> None:
        """ValidationError triggers retries; on exhaustion returns empty model."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        # Return malformed confidence (out of range) to trigger ValidationError
        bad_response = {
            "summary": "test",
            "fields": {"title": {"value": "T", "confidence": 9.9}},
        }
        gateway = _make_gateway_mock(bad_response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("set title to T")

        assert meta.parse_success is False
        assert result.fields == {}
        assert gateway.complete_json.call_count == FieldExtractionService.MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_retry_count_reflects_actual_attempts(self) -> None:
        """retry_count in meta equals the number of failed attempts."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        gateway = MagicMock()
        gateway.model = "gpt-4o-mini"
        # Fail first two attempts, succeed on third
        success_response = _llm_response(
            fields={"title": {"value": "T", "confidence": 0.9}}
        )
        gateway.complete_json = AsyncMock(
            side_effect=[
                json.JSONDecodeError("bad", "", 0),
                json.JSONDecodeError("bad", "", 0),
                (success_response, 40, 20, 80),
            ]
        )
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("title is T")

        assert meta.parse_success is True
        assert meta.retry_count == 2  # 0-indexed: third attempt = index 2
        assert "title" in result.fields

    @pytest.mark.asyncio
    async def test_non_parse_error_does_not_retry(self) -> None:
        """Network / API errors break the loop immediately (no point retrying)."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        gateway = MagicMock()
        gateway.model = "gpt-4o-mini"
        gateway.complete_json = AsyncMock(side_effect=RuntimeError("connection timeout"))
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("create handover")

        assert meta.parse_success is False
        assert result.fields == {}
        assert gateway.complete_json.call_count == 1  # no retry for RuntimeError

    @pytest.mark.asyncio
    async def test_workflow_stage_forwarded_to_user_content(self) -> None:
        """workflow_stage is appended to the LLM user content when provided."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(fields={})
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        await service.extract("create SR", workflow_stage="CREATE_SR")

        call_args = gateway.complete_json.call_args
        user_message_arg = call_args[1]["user_message"] if call_args[1] else call_args[0][1]
        assert "CREATE_SR" in user_message_arg

    @pytest.mark.asyncio
    async def test_all_backend_only_fields_stripped_by_service(self) -> None:
        """Service must strip every BACKEND_ONLY_FIELDS key regardless of what LLM returns."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={
                **{k: {"value": "x", "confidence": 1.0} for k in BACKEND_ONLY_FIELDS},
                "title": {"value": "Keep me", "confidence": 1.0},
            }
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, meta = await service.extract("inject all backend fields")

        assert meta.parse_success is True
        for bad_key in BACKEND_ONLY_FIELDS:
            assert bad_key not in result.fields
        assert "title" in result.fields

    @pytest.mark.asyncio
    async def test_inspection_done_by_fm_manager(self) -> None:
        """inspection_done_by normalized to FM_MANAGER is accepted."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={"inspection_done_by": {"value": "FM_MANAGER", "confidence": 0.9}}
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, _ = await service.extract("inspection done by FM manager")

        assert result.fields["inspection_done_by"].value == "FM_MANAGER"

    @pytest.mark.asyncio
    async def test_inspection_done_by_operations(self) -> None:
        """inspection_done_by normalized to OPERATIONS is accepted."""
        from app.agents.services.field_extraction_service import FieldExtractionService

        response = _llm_response(
            fields={"inspection_done_by": {"value": "OPERATIONS", "confidence": 0.85}}
        )
        gateway = _make_gateway_mock(response)
        service = FieldExtractionService(gateway=gateway)

        result, _ = await service.extract("inspection done by ops team")

        assert result.fields["inspection_done_by"].value == "OPERATIONS"


# ---------------------------------------------------------------------------
# FieldExtractionNode
# ---------------------------------------------------------------------------


class TestFieldExtractionNode:
    @pytest.mark.asyncio
    async def test_extracted_fields_written_to_state(self) -> None:
        """Node must return extracted_fields in the state update."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(
            fields={
                "title": {"value": "Handover SR", "confidence": 0.95},
                "mall": {"value": "Cenomi Mall", "confidence": 0.9},
            }
        )
        state = _base_state(user_message="Title: Handover SR at Cenomi Mall")

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=_make_gateway_mock(response),
        ):
            result = await field_extraction_node(state)

        assert "extracted_fields" in result
        assert "title" in result["extracted_fields"]
        assert "mall" in result["extracted_fields"]
        assert result["extracted_fields"]["title"]["value"] == "Handover SR"

    @pytest.mark.asyncio
    async def test_no_merge_into_collected_data(self) -> None:
        """Node must NOT write to collected_data — that belongs to merge_state_node."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(
            fields={"title": {"value": "Some SR", "confidence": 0.9}}
        )
        state = _base_state(user_message="title is Some SR")

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=_make_gateway_mock(response),
        ):
            result = await field_extraction_node(state)

        assert "collected_data" not in result

    @pytest.mark.asyncio
    async def test_trace_manager_absent_path(self) -> None:
        """Node runs correctly when trace_manager is not in state."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(
            fields={"lease_code": {"value": "LC-001", "confidence": 1.0}}
        )
        state = _base_state(user_message="lease code LC-001")
        # No trace_manager key — exercises the no-tracing code path.
        assert "trace_manager" not in state

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=_make_gateway_mock(response),
        ):
            result = await field_extraction_node(state)

        assert "extracted_fields" in result
        assert "lease_code" in result["extracted_fields"]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty_extracted_fields(self) -> None:
        """On LLM failure the node must not raise and must return empty extracted_fields."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        gateway = MagicMock()
        gateway.model = "gpt-4o-mini"
        gateway.complete_json = AsyncMock(side_effect=RuntimeError("API down"))

        state = _base_state(user_message="any message")

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=gateway,
        ):
            result = await field_extraction_node(state)

        assert isinstance(result, dict)
        assert result.get("extracted_fields") == {}

    @pytest.mark.asyncio
    async def test_backend_only_fields_never_reach_state(self) -> None:
        """Even if the LLM injects backend-only fields, they must be absent from state."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(
            fields={
                "brand": {"value": "Zara", "confidence": 0.9},
                "tenant_profile_id": {"value": "9999", "confidence": 1.0},
                "lease_id": {"value": "LEASE-XYZ", "confidence": 1.0},
            }
        )
        state = _base_state(user_message="brand is Zara")

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=_make_gateway_mock(response),
        ):
            result = await field_extraction_node(state)

        fields = result.get("extracted_fields", {})
        assert "brand" in fields
        assert "tenant_profile_id" not in fields
        assert "lease_id" not in fields

    @pytest.mark.asyncio
    async def test_confidence_stored_alongside_value(self) -> None:
        """extracted_fields must carry both value and confidence for merge_state_node."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(
            fields={"description": {"value": "Fit-out complete", "confidence": 0.88}}
        )
        state = _base_state(user_message="description: Fit-out complete")

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=_make_gateway_mock(response),
        ):
            result = await field_extraction_node(state)

        desc = result["extracted_fields"]["description"]
        assert desc["value"] == "Fit-out complete"
        assert desc["confidence"] == 0.88

    @pytest.mark.asyncio
    async def test_workflow_stage_passed_to_service(self) -> None:
        """workflow_stage from state is forwarded to the extraction service."""
        from app.agents.graph.nodes.field_extraction_node import field_extraction_node

        response = _llm_response(fields={})
        gateway = _make_gateway_mock(response)
        state = _base_state(
            user_message="ready for handover",
            workflow_stage="FM_REVIEW",
        )

        with patch(
            "app.agents.graph.nodes.field_extraction_node.get_default_gateway",
            return_value=gateway,
        ):
            await field_extraction_node(state)

        call_args = gateway.complete_json.call_args
        user_msg = call_args[1]["user_message"] if call_args[1] else call_args[0][1]
        assert "FM_REVIEW" in user_msg
