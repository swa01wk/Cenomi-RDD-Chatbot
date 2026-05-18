"""Unit tests — MissingFieldService: get_missing_fields and HANDOVER_FIELD_QUESTIONS.

Test groups
-----------
TestGetMissingFields       — All four "missing" rules (absent key, None, "", []) plus
                             positive cases and mixed scenarios.
TestHandoverFieldQuestions — Completeness and content spot-checks of the question map.
TestMissingFieldServiceClass — Backward-compat next_prompt behaviour.
"""

from __future__ import annotations

import pytest

from app.agents.services.missing_field_service import (
    HANDOVER_FIELD_QUESTIONS,
    MissingFieldService,
    get_missing_fields,
)


# ---------------------------------------------------------------------------
# TestGetMissingFields
# ---------------------------------------------------------------------------


class TestGetMissingFields:
    # ── Missing rules ──────────────────────────────────────────────────────

    def test_missing_when_key_absent(self) -> None:
        """Key not present in data → missing."""
        result = get_missing_fields({}, ["title"])
        assert result == ["title"]

    def test_missing_when_value_is_none(self) -> None:
        """Explicit None value → missing."""
        result = get_missing_fields({"title": None}, ["title"])
        assert result == ["title"]

    def test_missing_when_value_is_empty_string(self) -> None:
        """Empty string → missing."""
        result = get_missing_fields({"title": ""}, ["title"])
        assert result == ["title"]

    def test_missing_when_value_is_empty_list(self) -> None:
        """Empty list → missing."""
        result = get_missing_fields({"unit_codes": []}, ["unit_codes"])
        assert result == ["unit_codes"]

    # ── Present rules ──────────────────────────────────────────────────────

    def test_not_missing_when_string_value_present(self) -> None:
        """Non-empty string → not missing."""
        result = get_missing_fields({"title": "My SR"}, ["title"])
        assert result == []

    def test_not_missing_when_non_empty_list(self) -> None:
        """Non-empty list → not missing."""
        result = get_missing_fields({"unit_codes": ["U-01"]}, ["unit_codes"])
        assert result == []

    def test_not_missing_when_zero_integer(self) -> None:
        """Integer 0 is a valid value (not empty string / list) → not missing."""
        result = get_missing_fields({"contracted_area": 0}, ["contracted_area"])
        assert result == []

    def test_not_missing_when_false_boolean(self) -> None:
        """False boolean is a valid value → not missing."""
        result = get_missing_fields({"confirmation_required": False}, ["confirmation_required"])
        assert result == []

    # ── Multiple required fields ───────────────────────────────────────────

    def test_all_required_fields_missing(self) -> None:
        result = get_missing_fields({}, ["title", "description", "startDate"])
        assert set(result) == {"title", "description", "startDate"}

    def test_subset_missing(self) -> None:
        data = {"title": "SR", "description": "", "startDate": None}
        result = get_missing_fields(data, ["title", "description", "startDate"])
        assert set(result) == {"description", "startDate"}

    def test_all_present_returns_empty(self) -> None:
        data = {"title": "SR", "startDate": "2025-01-01", "endDate": "2025-01-31"}
        result = get_missing_fields(data, ["title", "startDate", "endDate"])
        assert result == []

    def test_empty_required_list_returns_empty(self) -> None:
        result = get_missing_fields({"title": "SR"}, [])
        assert result == []

    def test_preserves_required_fields_order(self) -> None:
        """Missing fields should appear in the same order as required_fields."""
        required = ["a", "b", "c", "d"]
        data = {"b": "present"}
        result = get_missing_fields(data, required)
        assert result == ["a", "c", "d"]

    def test_extra_keys_in_data_ignored(self) -> None:
        """Keys in data beyond required_fields are irrelevant."""
        data = {"title": "SR", "extra_key": "value"}
        result = get_missing_fields(data, ["title"])
        assert result == []


# ---------------------------------------------------------------------------
# TestHandoverFieldQuestions
# ---------------------------------------------------------------------------


class TestHandoverFieldQuestions:
    _EXPECTED_FIELDS = {
        "lease_code",
        "lease_brand_mall",
        "title",
        "description",
        "startDate",
        "endDate",
        "inspection_done_by",
        "comments",
        "unit_readiness_date",
        "expected_handover_date",
        "guideLineLink",
        "actual_handover_date",
        "fitout_start_date",
        "fitout_end_date",
        "trading_date",
    }

    def test_all_expected_fields_present(self) -> None:
        assert self._EXPECTED_FIELDS <= set(HANDOVER_FIELD_QUESTIONS.keys())

    def test_all_values_are_non_empty_strings(self) -> None:
        for field, question in HANDOVER_FIELD_QUESTIONS.items():
            assert isinstance(question, str) and question, (
                f"Question for '{field}' must be a non-empty string"
            )

    def test_lease_code_question_content(self) -> None:
        assert "lease code" in HANDOVER_FIELD_QUESTIONS["lease_code"].lower()

    def test_lease_brand_mall_question_content(self) -> None:
        q = HANDOVER_FIELD_QUESTIONS["lease_brand_mall"].lower()
        assert any(word in q for word in ("lease", "brand", "mall"))

    def test_inspection_done_by_mentions_fm_or_operations(self) -> None:
        q = HANDOVER_FIELD_QUESTIONS["inspection_done_by"].lower()
        assert "fm" in q or "operations" in q

    def test_questions_end_with_punctuation(self) -> None:
        """Every question must end with '?' or '.' — no bare open sentences."""
        for field, question in HANDOVER_FIELD_QUESTIONS.items():
            assert question.endswith("?") or question.endswith("."), (
                f"Question for '{field}' must end with '?' or '.': {question!r}"
            )


# ---------------------------------------------------------------------------
# TestMissingFieldServiceClass
# ---------------------------------------------------------------------------


class TestMissingFieldServiceClass:
    def test_next_prompt_returns_none_when_no_issues(self) -> None:
        service = MissingFieldService()
        assert service.next_prompt([]) is None

    def test_next_prompt_returns_string_when_issues_exist(self) -> None:
        from app.types.service_request import ValidationIssueDTO

        service = MissingFieldService()
        issues = [ValidationIssueDTO(code="MISSING", message="title required", field_key="title")]
        result = service.next_prompt(issues)
        assert isinstance(result, str) and result
