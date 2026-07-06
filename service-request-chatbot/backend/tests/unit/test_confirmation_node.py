"""Unit tests — confirmation_node and _build_confirmation_card.

Test groups
-----------
TestBuildConfirmationCard    — Card shape, field ordering, label mapping, values.
TestConfirmationNodeSkip     — Node is a no-op when required fields are missing.
TestConfirmationNodeReady    — Node generates the full card when all fields present.
TestConfirmationNodeImmutable — Node never mutates collected_data.
TestConfirmationNodeStage    — Workflow stage defaulting and custom stage support.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.graph.nodes.handover.confirmation_node import (
    _CONFIRMATION_DISPLAY_FIELDS,
    _build_confirmation_card,
    confirmation_node,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _minimal_create_sr() -> dict[str, Any]:
    """Minimal complete ``collected_data`` for the CREATE_SR stage."""
    return {
        "tenant_profile_id": "TP-001",
        "property_id": "PROP-001",
        "lease_code": "LC-001",
        "lease_id": "LEASE-001",
        "brand_id": "BR-001",
        "mall": "Riyadh Park",
        "brand": "Nike",
        "lease": "Lease A",
        "unit_codes": ["U-01"],
        "city": "Riyadh",
        "contracted_area": 150,
        "title": "Handover SR",
        "description": "Tenant handover request",
        "startDate": "2025-03-01",
        "endDate": "2025-09-01",
        "inspection_done_by": "FM_MANAGER",
        "comments": "Ready for handover",
    }


# ===========================================================================
# TestBuildConfirmationCard
# ===========================================================================


class TestBuildConfirmationCard:
    def test_returns_dict(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        assert isinstance(card, dict)

    def test_type_is_confirmation_card(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        assert card["type"] == "confirmation_card"

    def test_fields_key_is_list(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        assert isinstance(card["fields"], list)

    def test_fields_count_matches_display_fields(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        assert len(card["fields"]) == len(_CONFIRMATION_DISPLAY_FIELDS)

    def test_fields_order_matches_display_fields(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        keys = [f["key"] for f in card["fields"]]
        assert keys == list(_CONFIRMATION_DISPLAY_FIELDS)

    def test_each_field_has_key_label_value(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        for field in card["fields"]:
            assert "key" in field
            assert "label" in field
            assert "value" in field

    def test_field_values_match_collected_data(self) -> None:
        data = _minimal_create_sr()
        card = _build_confirmation_card(data, "CREATE_SR")
        for field in card["fields"]:
            assert field["value"] == data.get(field["key"])

    def test_lease_code_label(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        lc = next(f for f in card["fields"] if f["key"] == "lease_code")
        assert lc["label"] == "Lease Code"

    def test_unit_codes_value_is_list(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        uc = next(f for f in card["fields"] if f["key"] == "unit_codes")
        assert uc["value"] == ["U-01"]

    def test_contracted_area_numeric_value(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        ca = next(f for f in card["fields"] if f["key"] == "contracted_area")
        assert ca["value"] == 150

    def test_message_key_present(self) -> None:
        card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        assert "message" in card
        assert isinstance(card["message"], str)
        assert len(card["message"]) > 0

    def test_missing_display_field_value_is_none(self) -> None:
        """A display field absent from collected_data should have value=None."""
        data = _minimal_create_sr()
        del data["comments"]
        card = _build_confirmation_card(data, "CREATE_SR")
        comments = next(f for f in card["fields"] if f["key"] == "comments")
        assert comments["value"] is None

    def test_deterministic_same_input_same_output(self) -> None:
        data = _minimal_create_sr()
        assert _build_confirmation_card(data, "CREATE_SR") == _build_confirmation_card(data, "CREATE_SR")

    def test_different_data_different_card(self) -> None:
        data1 = _minimal_create_sr()
        data2 = _minimal_create_sr()
        data2["title"] = "Different Title"
        assert _build_confirmation_card(data1, "CREATE_SR") != _build_confirmation_card(data2, "CREATE_SR")


# ===========================================================================
# TestConfirmationNodeSkip
# ===========================================================================


class TestConfirmationNodeSkip:
    @pytest.mark.asyncio
    async def test_returns_empty_when_all_fields_missing(self) -> None:
        state: dict[str, Any] = {"collected_data": {}, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_partial_fields(self) -> None:
        data = _minimal_create_sr()
        del data["title"]
        del data["description"]
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_one_field_missing(self) -> None:
        data = _minimal_create_sr()
        del data["comments"]
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_collected_data_absent(self) -> None:
        state: dict[str, Any] = {"workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_field_value_is_empty_string(self) -> None:
        data = _minimal_create_sr()
        data["title"] = ""
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_field_value_is_none(self) -> None:
        data = _minimal_create_sr()
        data["startDate"] = None
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_unit_codes_is_empty_list(self) -> None:
        data = _minimal_create_sr()
        data["unit_codes"] = []
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        assert result == {}


# ===========================================================================
# TestConfirmationNodeReady
# ===========================================================================


class TestConfirmationNodeReady:
    @pytest.mark.asyncio
    async def test_confirmation_required_is_true(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert result["confirmation_required"] is True

    @pytest.mark.asyncio
    async def test_confirmation_status_is_pending(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert result["confirmation_status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_status_is_ready_to_submit(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert result["status"] == "READY_TO_SUBMIT"

    @pytest.mark.asyncio
    async def test_response_ui_type_is_confirmation_card(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert result["response_ui"]["type"] == "confirmation_card"

    @pytest.mark.asyncio
    async def test_response_ui_has_fields(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert isinstance(result["response_ui"]["fields"], list)
        assert len(result["response_ui"]["fields"]) > 0

    @pytest.mark.asyncio
    async def test_response_ui_fields_contain_display_fields(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        keys = {f["key"] for f in result["response_ui"]["fields"]}
        assert keys == set(_CONFIRMATION_DISPLAY_FIELDS)

    @pytest.mark.asyncio
    async def test_result_keys_are_complete(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        result = await confirmation_node(state)
        assert {"confirmation_required", "confirmation_status", "status", "response_ui"} <= result.keys()

    @pytest.mark.asyncio
    async def test_confirmation_card_reflects_collected_data(self) -> None:
        data = _minimal_create_sr()
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        fields_by_key = {f["key"]: f["value"] for f in result["response_ui"]["fields"]}
        assert fields_by_key["lease_code"] == data["lease_code"]
        assert fields_by_key["brand"] == data["brand"]
        assert fields_by_key["mall"] == data["mall"]
        assert fields_by_key["unit_codes"] == data["unit_codes"]
        assert fields_by_key["city"] == data["city"]
        assert fields_by_key["contracted_area"] == data["contracted_area"]
        assert fields_by_key["title"] == data["title"]
        assert fields_by_key["description"] == data["description"]
        assert fields_by_key["startDate"] == data["startDate"]
        assert fields_by_key["endDate"] == data["endDate"]
        assert fields_by_key["inspection_done_by"] == data["inspection_done_by"]
        assert fields_by_key["comments"] == data["comments"]

    @pytest.mark.asyncio
    async def test_deterministic_output(self) -> None:
        data = _minimal_create_sr()
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        r1 = await confirmation_node(state)
        r2 = await confirmation_node(state)
        assert r1 == r2

    @pytest.mark.asyncio
    async def test_integer_zero_contracted_area_is_valid(self) -> None:
        """contracted_area = 0 is a valid value — must not be treated as missing."""
        data = _minimal_create_sr()
        data["contracted_area"] = 0
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        result = await confirmation_node(state)
        # contracted_area=0 is a required field that is present, so other missing
        # fields should still be the deciding factor; here all fields are present.
        assert result["confirmation_required"] is True


# ===========================================================================
# TestConfirmationNodeImmutable
# ===========================================================================


class TestConfirmationNodeImmutable:
    @pytest.mark.asyncio
    async def test_does_not_modify_collected_data(self) -> None:
        data = _minimal_create_sr()
        original_data = dict(data)
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "CREATE_SR"}
        await confirmation_node(state)
        assert data == original_data

    @pytest.mark.asyncio
    async def test_does_not_modify_state(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "CREATE_SR",
        }
        original_keys = set(state.keys())
        await confirmation_node(state)
        assert set(state.keys()) == original_keys


# ===========================================================================
# TestConfirmationNodeStage
# ===========================================================================


class TestConfirmationNodeStage:
    @pytest.mark.asyncio
    async def test_defaults_to_create_sr_stage_when_absent(self) -> None:
        state: dict[str, Any] = {"collected_data": _minimal_create_sr()}
        result = await confirmation_node(state)
        assert result["status"] == "READY_TO_SUBMIT"

    @pytest.mark.asyncio
    async def test_empty_workflow_stage_defaults_to_create_sr(self) -> None:
        state: dict[str, Any] = {
            "collected_data": _minimal_create_sr(),
            "workflow_stage": "",
        }
        result = await confirmation_node(state)
        assert result["status"] == "READY_TO_SUBMIT"

    @pytest.mark.asyncio
    async def test_fm_review_stage_returns_empty_for_create_sr_data(self) -> None:
        """FM_REVIEW requires different fields; CREATE_SR data should be incomplete."""
        data = _minimal_create_sr()
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "FM_REVIEW"}
        result = await confirmation_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_fm_review_stage_ready_when_fields_present(self) -> None:
        data = {
            "unit_readiness_date": "2025-04-01",
            "expected_handover_date": "2025-05-01",
        }
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "FM_REVIEW"}
        result = await confirmation_node(state)
        assert result["confirmation_required"] is True
        assert result["status"] == "READY_TO_SUBMIT"


# ===========================================================================
# TestStageSpecificConfirmationCards (NEW — covers FM_REVIEW and RDD_REVIEW)
# ===========================================================================


def _minimal_fm_review() -> dict[str, Any]:
    """Minimum collected_data that satisfies FM_REVIEW required fields."""
    return {
        "unit_readiness_date": "2026-07-10",
        # expected_handover_date auto-computed but fine to include for card tests
        "expected_handover_date": "2026-07-17",
        "lease_code": "t0105712",
        "brand": "Brand Under Armour",
        "mall": "Jawharat Jeddah",
    }


def _minimal_rdd_review() -> dict[str, Any]:
    """Minimum collected_data that satisfies RDD_REVIEW required fields."""
    return {
        "guideLineLink": "https://cenomi.com/guidelines",
        "actual_handover_date": "2026-07-15",
        "fitout_start_date": "2026-07-16",
        "fitout_end_date": "2026-07-20",
        "trading_date": "2026-07-28",
        "lease_code": "t0105712",
        "brand": "Brand Under Armour",
        "mall": "Jawharat Jeddah",
    }


class TestStageSpecificConfirmationCards:
    """Confirm that _build_confirmation_card produces stage-appropriate field sets."""

    # ── FM_REVIEW card ──────────────────────────────────────────────────────

    def test_fm_card_contains_unit_readiness_date(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        assert "unit_readiness_date" in keys

    def test_fm_card_contains_expected_handover_date(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        assert "expected_handover_date" in keys

    def test_fm_card_does_not_contain_create_sr_only_fields(self) -> None:
        """FM card must NOT show CREATE_SR-only fields like description or startDate."""
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        assert "description" not in keys
        assert "startDate" not in keys
        assert "endDate" not in keys
        assert "inspection_done_by" not in keys

    def test_fm_card_request_type_label(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        assert card["requestType"] == "FM Review — Save / Approve"

    def test_fm_card_stage_field(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        assert card["stage"] == "FM_REVIEW"

    def test_fm_card_message_is_fm_specific(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        assert "FM" in card["message"] or "readiness" in card["message"].lower()

    def test_fm_card_unit_readiness_editable(self) -> None:
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        urd = next(f for f in card["fields"] if f["key"] == "unit_readiness_date")
        assert urd["editable"] is True

    def test_fm_card_expected_handover_not_editable(self) -> None:
        """expected_handover_date is auto-computed — should not be editable."""
        card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        ehd = next(f for f in card["fields"] if f["key"] == "expected_handover_date")
        assert ehd["editable"] is False

    # ── RDD_REVIEW card ─────────────────────────────────────────────────────

    def test_rdd_card_contains_guide_line_link(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        assert "guideLineLink" in keys

    def test_rdd_card_contains_all_rdd_dates(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        for expected in ("actual_handover_date", "fitout_start_date", "fitout_end_date", "trading_date"):
            assert expected in keys, f"Expected key '{expected}' missing from RDD card"

    def test_rdd_card_does_not_contain_create_sr_fields(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        keys = {f["key"] for f in card["fields"]}
        assert "startDate" not in keys
        assert "endDate" not in keys
        assert "inspection_done_by" not in keys

    def test_rdd_card_request_type_label(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        assert card["requestType"] == "RDD Report Submission"

    def test_rdd_card_stage_field(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        assert card["stage"] == "RDD_REVIEW"

    def test_rdd_card_dates_are_editable(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        editable_keys = {f["key"] for f in card["fields"] if f["editable"]}
        for date_key in ("actual_handover_date", "fitout_start_date", "fitout_end_date", "trading_date"):
            assert date_key in editable_keys

    def test_rdd_card_guide_link_is_editable(self) -> None:
        card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        gl = next(f for f in card["fields"] if f["key"] == "guideLineLink")
        assert gl["editable"] is True

    def test_rdd_card_values_match_collected_data(self) -> None:
        data = _minimal_rdd_review()
        card = _build_confirmation_card(data, "RDD_REVIEW")
        fields_by_key = {f["key"]: f["value"] for f in card["fields"]}
        assert fields_by_key["guideLineLink"] == data["guideLineLink"]
        assert fields_by_key["actual_handover_date"] == data["actual_handover_date"]
        assert fields_by_key["trading_date"] == data["trading_date"]

    # ── Stage isolation ─────────────────────────────────────────────────────

    def test_create_sr_and_fm_cards_have_different_fields(self) -> None:
        create_card = _build_confirmation_card(_minimal_create_sr(), "CREATE_SR")
        fm_card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        create_keys = {f["key"] for f in create_card["fields"]}
        fm_keys = {f["key"] for f in fm_card["fields"]}
        assert create_keys != fm_keys

    def test_fm_and_rdd_cards_have_different_fields(self) -> None:
        fm_card = _build_confirmation_card(_minimal_fm_review(), "FM_REVIEW")
        rdd_card = _build_confirmation_card(_minimal_rdd_review(), "RDD_REVIEW")
        fm_keys = {f["key"] for f in fm_card["fields"]}
        rdd_keys = {f["key"] for f in rdd_card["fields"]}
        # guideLineLink only in RDD; unit_readiness_date only in FM
        assert "guideLineLink" in rdd_keys and "guideLineLink" not in fm_keys
        assert "unit_readiness_date" in fm_keys and "unit_readiness_date" not in rdd_keys

    def test_unknown_stage_falls_back_to_create_sr_fields(self) -> None:
        """An unrecognised stage should fall back to CREATE_SR display config."""
        data = _minimal_create_sr()
        card = _build_confirmation_card(data, "UNKNOWN_STAGE")
        create_keys = {f["key"] for f in _build_confirmation_card(data, "CREATE_SR")["fields"]}
        unknown_keys = {f["key"] for f in card["fields"]}
        assert unknown_keys == create_keys

    # ── Node-level FM/RDD card tests ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_node_generates_fm_card_for_fm_review_stage(self) -> None:
        data = _minimal_fm_review()
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "FM_REVIEW"}
        result = await confirmation_node(state)
        assert result.get("confirmation_required") is True
        assert result["response_ui"]["stage"] == "FM_REVIEW"
        card_keys = {f["key"] for f in result["response_ui"]["fields"]}
        assert "unit_readiness_date" in card_keys
        assert "startDate" not in card_keys

    @pytest.mark.asyncio
    async def test_node_generates_rdd_card_for_rdd_review_stage(self) -> None:
        data = _minimal_rdd_review()
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "RDD_REVIEW"}
        result = await confirmation_node(state)
        assert result.get("confirmation_required") is True
        assert result["response_ui"]["stage"] == "RDD_REVIEW"
        card_keys = {f["key"] for f in result["response_ui"]["fields"]}
        assert "guideLineLink" in card_keys
        assert "actual_handover_date" in card_keys

    @pytest.mark.asyncio
    async def test_node_skips_rdd_when_required_field_missing(self) -> None:
        """Missing guideLineLink should prevent RDD confirmation card from appearing."""
        data = _minimal_rdd_review()
        del data["guideLineLink"]
        state: dict[str, Any] = {"collected_data": data, "workflow_stage": "RDD_REVIEW"}
        result = await confirmation_node(state)
        assert result == {}
