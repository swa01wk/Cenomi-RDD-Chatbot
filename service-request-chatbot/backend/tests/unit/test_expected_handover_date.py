"""Unit tests for expected_handover_date auto-calculation.

Coverage
--------
_add_days helper:
  - Basic 7-day addition (YYYY-MM-DD input)
  - Month boundary (Jan → Feb)
  - Year boundary (Dec → Jan)
  - DD/MM/YYYY input format accepted
  - DD-MM-YYYY input format accepted
  - Invalid / non-date string returned unchanged

handover_schema.py changes:
  - expected_handover_date removed from FM_REVIEW_STAGE.required_fields
  - BACKEND_COMPUTED_FIELDS constant exists and contains expected_handover_date
  - get_missing_fields("FM_REVIEW", {readiness set}) returns []
  - get_missing_fields("FM_REVIEW", {}) returns ["unit_readiness_date"]

merge_state_node auto-calc:
  - FM_REVIEW + unit_readiness_date set → expected_handover_date auto-computed
  - Correct +7 days result stored in collected_data
  - Auto-calc does NOT fire for CREATE_SR or RDD_REVIEW stages
  - Auto-calc does NOT overwrite an existing expected_handover_date
  - Auto-calc fires even when extracted_fields is empty (action path)
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.graph.nodes.merge_state_node import _add_days, merge_state_node
from app.agents.schemas.handover_schema import (
    BACKEND_COMPUTED_FIELDS,
    FM_REVIEW_STAGE,
    get_missing_fields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-date-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "extracted_fields": {},
        "corrected_fields": {},
        "collected_data": {},
        "workflow_stage": "FM_REVIEW",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _add_days helper
# ---------------------------------------------------------------------------


class TestAddDays:
    def test_basic_7_days(self) -> None:
        assert _add_days("2026-06-18", 7) == "2026-06-25"

    def test_month_boundary_jan_to_feb(self) -> None:
        assert _add_days("2026-01-28", 7) == "2026-02-04"

    def test_month_boundary_feb_non_leap(self) -> None:
        assert _add_days("2026-02-22", 7) == "2026-03-01"

    def test_year_boundary_dec_to_jan(self) -> None:
        assert _add_days("2026-12-28", 7) == "2027-01-04"

    def test_ddmmyyyy_input_format(self) -> None:
        assert _add_days("18/06/2026", 7) == "2026-06-25"

    def test_dd_dash_mm_yyyy_input_format(self) -> None:
        assert _add_days("18-06-2026", 7) == "2026-06-25"

    def test_invalid_string_returned_unchanged(self) -> None:
        assert _add_days("not-a-date", 7) == "not-a-date"

    def test_empty_string_returned_unchanged(self) -> None:
        assert _add_days("", 7) == ""

    def test_zero_days(self) -> None:
        assert _add_days("2026-06-18", 0) == "2026-06-18"

    def test_result_is_iso_format(self) -> None:
        result = _add_days("2026-06-18", 7)
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # YYYY


# ---------------------------------------------------------------------------
# Schema: expected_handover_date removed from FM_REVIEW_STAGE
# ---------------------------------------------------------------------------


class TestHandoverSchemaFix:
    def test_expected_handover_date_not_in_fm_required_fields(self) -> None:
        assert "expected_handover_date" not in FM_REVIEW_STAGE.required_fields

    def test_unit_readiness_date_still_in_fm_required_fields(self) -> None:
        assert "unit_readiness_date" in FM_REVIEW_STAGE.required_fields

    def test_backend_computed_fields_constant_exists(self) -> None:
        assert BACKEND_COMPUTED_FIELDS is not None

    def test_expected_handover_date_in_backend_computed_fields(self) -> None:
        assert "expected_handover_date" in BACKEND_COMPUTED_FIELDS

    def test_get_missing_fields_fm_with_readiness_set(self) -> None:
        """When unit_readiness_date is provided, FM_REVIEW has no missing fields."""
        collected = {"unit_readiness_date": "2026-06-18"}
        missing = get_missing_fields("FM_REVIEW", collected)
        assert missing == []

    def test_get_missing_fields_fm_without_readiness(self) -> None:
        """Empty collected_data → only unit_readiness_date is missing."""
        missing = get_missing_fields("FM_REVIEW", {})
        assert "unit_readiness_date" in missing

    def test_get_missing_fields_fm_empty_readiness_still_missing(self) -> None:
        """Empty-string unit_readiness_date still counts as missing."""
        missing = get_missing_fields("FM_REVIEW", {"unit_readiness_date": ""})
        assert "unit_readiness_date" in missing

    def test_expected_handover_date_not_in_missing_fields_result(self) -> None:
        """expected_handover_date must never appear in the missing fields list."""
        missing = get_missing_fields("FM_REVIEW", {})
        assert "expected_handover_date" not in missing


# ---------------------------------------------------------------------------
# merge_state_node auto-calculation
# ---------------------------------------------------------------------------


class TestMergeStateAutoCalc:
    @pytest.mark.asyncio
    async def test_fm_review_auto_computes_handover_date(self) -> None:
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={"unit_readiness_date": "2026-06-18"},
        )
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-06-25"

    @pytest.mark.asyncio
    async def test_auto_calc_correct_value_month_boundary(self) -> None:
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={"unit_readiness_date": "2026-01-28"},
        )
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-02-04"

    @pytest.mark.asyncio
    async def test_auto_calc_does_not_fire_for_create_sr(self) -> None:
        state = _state(
            workflow_stage="CREATE_SR",
            collected_data={"unit_readiness_date": "2026-06-18"},
        )
        result = await merge_state_node(state)
        assert "expected_handover_date" not in result["collected_data"]

    @pytest.mark.asyncio
    async def test_auto_calc_does_not_fire_for_rdd_review(self) -> None:
        state = _state(
            workflow_stage="RDD_REVIEW",
            collected_data={"unit_readiness_date": "2026-06-18"},
        )
        result = await merge_state_node(state)
        assert "expected_handover_date" not in result["collected_data"]

    @pytest.mark.asyncio
    async def test_auto_calc_does_not_overwrite_existing_value(self) -> None:
        """If expected_handover_date is already set, it must not be overwritten."""
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={
                "unit_readiness_date": "2026-06-18",
                "expected_handover_date": "2026-07-01",  # already set
            },
        )
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-07-01"

    @pytest.mark.asyncio
    async def test_auto_calc_without_readiness_date_no_error(self) -> None:
        """No unit_readiness_date → no auto-calc, no crash."""
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={},
        )
        result = await merge_state_node(state)
        assert "expected_handover_date" not in result["collected_data"]

    @pytest.mark.asyncio
    async def test_auto_calc_via_extracted_fields(self) -> None:
        """Auto-calc fires when readiness date arrives via extraction in same turn."""
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={},
            extracted_fields={"unit_readiness_date": {"value": "2026-06-18", "confidence": 0.9}},
        )
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-06-25"

    @pytest.mark.asyncio
    async def test_auto_calc_in_action_path_no_extraction(self) -> None:
        """Auto-calc fires even on action turns (no extracted_fields)."""
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={"unit_readiness_date": "2026-06-18"},
            extracted_fields={},  # action path — no LLM extraction
        )
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-06-25"
