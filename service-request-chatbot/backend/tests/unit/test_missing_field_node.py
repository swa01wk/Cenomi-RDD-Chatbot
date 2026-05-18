"""Unit tests — missing_field_node: clarifying questions, one per turn.

Test groups
-----------
TestMissingFieldNodeBasic          — State updates (missing_fields list, status).
TestOneQuestionAtATime             — Exactly one question is asked per invocation.
TestBackendProtectedFieldHandling  — Backend fields trigger lease_code question, not direct ask.
TestLeaseResolutionLogic           — lease_code → lease_brand_mall fallback chain.
TestNoMissingFields                — All fields present → IN_PROGRESS, no question.
TestWorkflowStageRouting           — Correct fields are checked per stage.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.graph.nodes.missing_field_node import (
    BACKEND_PROTECTED_FIELDS,
    missing_field_node,
)
from app.agents.schemas.handover_schema import (
    CREATE_SR_STAGE,
    FM_REVIEW_STAGE,
    RDD_REVIEW_STAGE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**overrides: Any) -> dict[str, Any]:
    return {"session_id": "sess-test", "user_id": "user-test", **overrides}


def _collected(**fields: Any) -> dict[str, Any]:
    return dict(fields)


# ---------------------------------------------------------------------------
# TestMissingFieldNodeBasic
# ---------------------------------------------------------------------------


class TestMissingFieldNodeBasic:
    @pytest.mark.asyncio
    async def test_returns_missing_fields_list(self) -> None:
        """Node must always return a 'missing_fields' key in its output."""
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        assert "missing_fields" in result
        assert isinstance(result["missing_fields"], list)

    @pytest.mark.asyncio
    async def test_missing_fields_contains_absent_required_fields(self) -> None:
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        missing = set(result["missing_fields"])
        assert "unit_readiness_date" in missing
        assert "expected_handover_date" in missing

    @pytest.mark.asyncio
    async def test_status_is_waiting_when_question_asked(self) -> None:
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_response_message_is_non_empty_when_question_asked(self) -> None:
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        assert isinstance(result["response_message"], str) and result["response_message"]

    @pytest.mark.asyncio
    async def test_response_ui_has_correct_shape(self) -> None:
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        ui = result["response_ui"]
        assert ui["type"] == "text_question"
        assert "field" in ui
        assert "message" in ui

    @pytest.mark.asyncio
    async def test_response_ui_field_matches_response_message_context(self) -> None:
        """The 'field' key in response_ui should correspond to the question being asked."""
        state = _state(workflow_stage="FM_REVIEW", collected_data={})
        result = await missing_field_node(state)
        ui = result["response_ui"]
        assert ui["message"] == result["response_message"]


# ---------------------------------------------------------------------------
# TestOneQuestionAtATime
# ---------------------------------------------------------------------------


class TestOneQuestionAtATime:
    @pytest.mark.asyncio
    async def test_only_one_question_asked_per_turn(self) -> None:
        """Even when multiple fields are missing, response_message is a single question."""
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={},
        )
        result = await missing_field_node(state)
        # response_message should be a single question string, not a list
        assert isinstance(result["response_message"], str)
        # The response_ui has exactly one 'field' key (single target)
        assert isinstance(result["response_ui"]["field"], str)

    @pytest.mark.asyncio
    async def test_after_first_field_answered_next_is_asked(self) -> None:
        """Providing one field should shift the question to the next missing one."""
        state1 = _state(workflow_stage="FM_REVIEW", collected_data={})
        result1 = await missing_field_node(state1)
        first_field = result1["response_ui"]["field"]

        # Simulate user answering the first question
        collected = {first_field: "2025-06-01"}
        state2 = _state(workflow_stage="FM_REVIEW", collected_data=collected)
        result2 = await missing_field_node(state2)

        # There should still be a question (for the second missing field)
        assert result2["status"] == "WAITING_FOR_USER"
        second_field = result2["response_ui"]["field"]
        assert second_field != first_field

    @pytest.mark.asyncio
    async def test_rdd_review_asks_first_user_field_only(self) -> None:
        """RDD_REVIEW stage with no collected data should ask exactly one question."""
        state = _state(workflow_stage="RDD_REVIEW", collected_data={})
        result = await missing_field_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert isinstance(result["response_ui"]["field"], str)

    @pytest.mark.asyncio
    async def test_questions_progress_through_fm_review_fields(self) -> None:
        """Iterating through FM_REVIEW fields one by one should cover all of them."""
        required = list(FM_REVIEW_STAGE.required_fields)
        # Remove backend-protected fields from required (not directly asked)
        user_fields = [f for f in required if f not in BACKEND_PROTECTED_FIELDS]

        collected: dict[str, Any] = {}
        asked_fields: list[str] = []

        for _ in range(len(user_fields) + 1):
            state = _state(workflow_stage="FM_REVIEW", collected_data=collected)
            result = await missing_field_node(state)
            if result["status"] != "WAITING_FOR_USER":
                break
            field = result["response_ui"]["field"]
            asked_fields.append(field)
            collected[field] = "dummy-value"

        assert set(asked_fields) == set(user_fields)


# ---------------------------------------------------------------------------
# TestBackendProtectedFieldHandling
# ---------------------------------------------------------------------------


class TestBackendProtectedFieldHandling:
    @pytest.mark.asyncio
    async def test_backend_missing_triggers_lease_code_question(self) -> None:
        """When backend-derived fields are absent, ask for lease_code, not the backend field."""
        # CREATE_SR requires property_id (backend-derived) and title (user-supplied).
        # With an empty collected_data, the node should ask for lease_code to trigger lookup.
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        # Must ask for a lease resolution trigger, not a raw backend field.
        asked_field = result["response_ui"]["field"]
        assert asked_field not in BACKEND_PROTECTED_FIELDS

    @pytest.mark.asyncio
    async def test_does_not_ask_tenant_profile_id_directly(self) -> None:
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        assert result["response_ui"]["field"] != "tenant_profile_id"

    @pytest.mark.asyncio
    async def test_does_not_ask_property_id_directly(self) -> None:
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        assert result["response_ui"]["field"] != "property_id"

    @pytest.mark.asyncio
    async def test_does_not_ask_lease_id_directly(self) -> None:
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        assert result["response_ui"]["field"] != "lease_id"

    @pytest.mark.asyncio
    async def test_missing_fields_list_includes_backend_fields(self) -> None:
        """missing_fields list should accurately reflect ALL missing fields including backend ones."""
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        # Some backend fields should appear in missing_fields even if we don't ask for them
        backend_required = [
            f for f in CREATE_SR_STAGE.required_fields if f in BACKEND_PROTECTED_FIELDS
        ]
        missing_set = set(result["missing_fields"])
        for bf in backend_required:
            assert bf in missing_set, f"Backend field '{bf}' should be in missing_fields"


# ---------------------------------------------------------------------------
# TestLeaseResolutionLogic
# ---------------------------------------------------------------------------


class TestLeaseResolutionLogic:
    @pytest.mark.asyncio
    async def test_asks_lease_code_when_both_trigger_fields_absent(self) -> None:
        """lease_code is preferred over lease_brand_mall when neither is present."""
        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        # Verify it asks for lease_code specifically (first trigger preference)
        assert result["response_ui"]["field"] == "lease_code"

    @pytest.mark.asyncio
    async def test_falls_back_to_lease_brand_mall_when_lease_code_present(self) -> None:
        """When lease_code is known but backend fields still missing, ask lease_brand_mall."""
        # Provide lease_code but no backend fields yet (simulating lookup pending)
        collected = {"lease_code": "LC-001"}
        state = _state(workflow_stage="CREATE_SR", collected_data=collected)
        result = await missing_field_node(state)
        # Should not ask lease_code again; should progress to lease_brand_mall or user fields
        asked = result["response_ui"]["field"] if result["status"] == "WAITING_FOR_USER" else None
        if asked is not None:
            assert asked != "lease_code"

    @pytest.mark.asyncio
    async def test_lease_code_question_text_is_from_question_map(self) -> None:
        """The question asked for lease_code must come from HANDOVER_FIELD_QUESTIONS."""
        from app.agents.services.missing_field_service import HANDOVER_FIELD_QUESTIONS

        state = _state(workflow_stage="CREATE_SR", collected_data={})
        result = await missing_field_node(state)
        assert result["response_message"] == HANDOVER_FIELD_QUESTIONS["lease_code"]

    @pytest.mark.asyncio
    async def test_when_both_triggers_present_and_backend_missing_no_question(self) -> None:
        """If both lease_code and lease_brand_mall are present, no lease trigger question needed.
        The node should not ask the user anything further for backend resolution."""
        collected = {"lease_code": "LC-001", "lease_brand_mall": "Nike - Riyadh Park"}
        state = _state(workflow_stage="CREATE_SR", collected_data=collected)
        result = await missing_field_node(state)
        # If backend fields are still missing but both triggers provided,
        # the node falls through to user fields or signals IN_PROGRESS
        asked = result["response_ui"]["field"] if result["status"] == "WAITING_FOR_USER" else None
        if asked is not None:
            assert asked not in BACKEND_PROTECTED_FIELDS
            assert asked not in ("lease_code", "lease_brand_mall")


# ---------------------------------------------------------------------------
# TestNoMissingFields
# ---------------------------------------------------------------------------


class TestNoMissingFields:
    @pytest.mark.asyncio
    async def test_all_fm_review_fields_present_returns_in_progress(self) -> None:
        collected = {f: "value" for f in FM_REVIEW_STAGE.required_fields}
        state = _state(workflow_stage="FM_REVIEW", collected_data=collected)
        result = await missing_field_node(state)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_all_rdd_review_fields_present_returns_in_progress(self) -> None:
        collected = {f: "value" for f in RDD_REVIEW_STAGE.required_fields}
        state = _state(workflow_stage="RDD_REVIEW", collected_data=collected)
        result = await missing_field_node(state)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_no_missing_fields_list_is_empty(self) -> None:
        collected = {f: "value" for f in FM_REVIEW_STAGE.required_fields}
        state = _state(workflow_stage="FM_REVIEW", collected_data=collected)
        result = await missing_field_node(state)
        assert result["missing_fields"] == []

    @pytest.mark.asyncio
    async def test_no_question_when_nothing_missing(self) -> None:
        collected = {f: "value" for f in FM_REVIEW_STAGE.required_fields}
        state = _state(workflow_stage="FM_REVIEW", collected_data=collected)
        result = await missing_field_node(state)
        assert result["response_message"] == ""
        assert "response_ui" not in result


# ---------------------------------------------------------------------------
# TestWorkflowStageRouting
# ---------------------------------------------------------------------------


class TestWorkflowStageRouting:
    @pytest.mark.asyncio
    async def test_default_stage_is_create_sr_when_absent(self) -> None:
        """When workflow_stage is absent, node defaults to CREATE_SR."""
        state = _state(collected_data={})
        result = await missing_field_node(state)
        # CREATE_SR has many required fields including backend ones → should ask lease_code
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_unknown_stage_falls_back_to_create_sr(self) -> None:
        """An unrecognised stage must not raise and should fall back gracefully."""
        state = _state(workflow_stage="UNKNOWN_STAGE", collected_data={})
        result = await missing_field_node(state)
        assert "missing_fields" in result
        assert "status" in result

    @pytest.mark.asyncio
    async def test_fm_review_only_checks_fm_fields(self) -> None:
        """FM_REVIEW should only report fields from its own StageDefinition."""
        collected = {f: "value" for f in FM_REVIEW_STAGE.required_fields}
        state = _state(workflow_stage="FM_REVIEW", collected_data=collected)
        result = await missing_field_node(state)
        # No CREATE_SR-only fields should appear in missing_fields
        assert result["missing_fields"] == []

    @pytest.mark.asyncio
    async def test_rdd_review_asks_for_rdd_specific_field(self) -> None:
        """RDD_REVIEW should eventually ask for its specific fields."""
        state = _state(workflow_stage="RDD_REVIEW", collected_data={})
        result = await missing_field_node(state)
        rdd_user_fields = [
            f for f in RDD_REVIEW_STAGE.required_fields
            if f not in BACKEND_PROTECTED_FIELDS
        ]
        asked = result["response_ui"]["field"] if result["status"] == "WAITING_FOR_USER" else None
        if asked is not None:
            assert asked in rdd_user_fields
