"""Unit tests — build_create_handover_payload and PayloadBuilderService.

Test groups
-----------
TestBuildCreateHandoverPayloadShape     — Top-level and inner payload structure.
TestBuildCreateHandoverPayloadValues    — All field values map correctly.
TestBuildCreateHandoverPayloadDefaults  — Optional / default fields.
TestBuildCreateHandoverPayloadValidation — Missing / empty key raises ValueError.
TestBuildCreateHandoverPayloadConstants — Static constants (service_category, etc.).
TestPayloadBuilderServiceClass          — Wrapper class delegation.
TestPayloadBuilderNodeIntegration       — Async node stores payload in backend_refs.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.services.payload_builder_service import (
    PayloadBuilderService,
    _REQUIRED_DATA_KEYS,
    build_create_handover_payload,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _full_data() -> dict[str, Any]:
    """Complete ``collected_data`` dict with all required keys present."""
    return {
        "mall": "Riyadh Park",
        "brand": "Nike",
        "lease_code": "LC-001",
        "lease_id": "LEASE-001",
        "title": "Handover SR",
        "endDate": "2025-09-01",
        "comments": "All good",
        "startDate": "2025-03-01",
        "description": "Tenant fit-out handover",
        "inspection_done_by": "FM_MANAGER",
        "lease_brand_mall": "LC-001|Nike|Riyadh Park",
        "unit_codes": ["U-01", "U-02"],
        "contracted_area": 200,
        "city": "Riyadh",
        "brand_id": "BR-001",
        "tenant_profile_id": "TP-001",
        "contract_id": "CONT-001",
        "property_id": "PROP-001",
        "notes": "Optional note",
        "startDateLT": "2025-03-01T00:00:00+03:00",
        "endDateLT": "2025-09-01T00:00:00+03:00",
    }


# ===========================================================================
# TestBuildCreateHandoverPayloadShape
# ===========================================================================


class TestBuildCreateHandoverPayloadShape:
    def test_returns_dict(self) -> None:
        assert isinstance(build_create_handover_payload(_full_data()), dict)

    def test_top_level_keys_present(self) -> None:
        result = build_create_handover_payload(_full_data())
        expected_top = {
            "payload",
            "title",
            "tenant_profile_id",
            "property_id",
            "service_category",
            "sub_category",
            "lease_code",
            "lease_id",
            "service_request_id",
        }
        assert expected_top <= result.keys()

    def test_inner_payload_is_dict(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert isinstance(result["payload"], dict)

    def test_inner_payload_has_all_expected_keys(self) -> None:
        result = build_create_handover_payload(_full_data())
        inner = result["payload"]
        expected = {
            "mall", "brand", "lease", "notes", "title", "endDate", "comments",
            "startDate", "attachments", "description", "documents_ids",
            "guideLineLink", "inspectionDoneBy", "lease_brand_mall",
            "inspection_done_by", "document_status_map", "unit_readiness_date",
            "expected_handover_date", "company_name", "tenant_contact",
            "user_action", "unit_codes", "contracted_area", "city", "brand_id",
            "tenant_profile_id", "contract_id", "property_id",
            "startDateLT", "endDateLT",
        }
        assert expected <= inner.keys()

    def test_service_request_id_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["service_request_id"] == ""

    def test_attachments_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["attachments"] == ""

    def test_documents_ids_is_empty_list(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["documents_ids"] == []

    def test_document_status_map_is_empty_list(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["document_status_map"] == []

    def test_guideline_link_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["guideLineLink"] == ""

    def test_user_action_is_none(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["user_action"] is None

    def test_unit_readiness_date_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["unit_readiness_date"] == ""

    def test_expected_handover_date_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["expected_handover_date"] == ""

    def test_tenant_contact_is_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["tenant_contact"] == ""

    def test_status_key_absent_from_payload(self) -> None:
        """status must never be sent during initial Mall Manager creation."""
        result = build_create_handover_payload(_full_data())
        assert "status" not in result
        assert "status" not in result["payload"]


# ===========================================================================
# TestBuildCreateHandoverPayloadValues
# ===========================================================================


class TestBuildCreateHandoverPayloadValues:
    def test_mall_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["mall"] == data["mall"]

    def test_brand_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["brand"] == data["brand"]

    def test_lease_code_mapped_to_lease(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["lease"] == data["lease_code"]

    def test_title_mapped_top_level_and_inner(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["title"] == data["title"]
        assert result["payload"]["title"] == data["title"]

    def test_start_date_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["startDate"] == data["startDate"]

    def test_end_date_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["endDate"] == data["endDate"]

    def test_comments_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["comments"] == data["comments"]

    def test_description_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["description"] == data["description"]

    def test_inspection_done_by_mapped_to_both_keys(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["inspectionDoneBy"] == data["inspection_done_by"]
        assert result["payload"]["inspection_done_by"] == data["inspection_done_by"]

    def test_lease_brand_mall_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["lease_brand_mall"] == data["lease_brand_mall"]

    def test_unit_codes_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["unit_codes"] == data["unit_codes"]

    def test_contracted_area_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["contracted_area"] == data["contracted_area"]

    def test_city_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["city"] == data["city"]

    def test_brand_id_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["brand_id"] == data["brand_id"]

    def test_tenant_profile_id_mapped_top_and_inner(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["tenant_profile_id"] == data["tenant_profile_id"]
        assert result["payload"]["tenant_profile_id"] == data["tenant_profile_id"]

    def test_contract_id_mapped(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["contract_id"] == data["contract_id"]

    def test_property_id_mapped_top_and_inner(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["property_id"] == data["property_id"]
        assert result["payload"]["property_id"] == data["property_id"]

    def test_lease_code_mapped_top_level(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["lease_code"] == data["lease_code"]

    def test_lease_id_mapped_top_level(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["lease_id"] == data["lease_id"]

    def test_company_name_is_str_of_tenant_profile_id(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["company_name"] == str(data["tenant_profile_id"])

    def test_company_name_coerces_int_to_str(self) -> None:
        data = _full_data()
        data["tenant_profile_id"] = 12345
        result = build_create_handover_payload(data)
        assert result["payload"]["company_name"] == "12345"
        assert isinstance(result["payload"]["company_name"], str)

    def test_notes_mapped_when_present(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["notes"] == data["notes"]

    def test_startDateLT_mapped_when_present(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["startDateLT"] == data["startDateLT"]

    def test_endDateLT_mapped_when_present(self) -> None:
        data = _full_data()
        result = build_create_handover_payload(data)
        assert result["payload"]["endDateLT"] == data["endDateLT"]


# ===========================================================================
# TestBuildCreateHandoverPayloadDefaults
# ===========================================================================


class TestBuildCreateHandoverPayloadDefaults:
    def test_notes_defaults_to_empty_string_when_absent(self) -> None:
        data = _full_data()
        del data["notes"]
        result = build_create_handover_payload(data)
        assert result["payload"]["notes"] == ""

    def test_startDateLT_defaults_to_empty_string_when_absent(self) -> None:
        data = _full_data()
        del data["startDateLT"]
        result = build_create_handover_payload(data)
        assert result["payload"]["startDateLT"] == ""

    def test_endDateLT_defaults_to_empty_string_when_absent(self) -> None:
        data = _full_data()
        del data["endDateLT"]
        result = build_create_handover_payload(data)
        assert result["payload"]["endDateLT"] == ""

    def test_all_optional_fields_absent_still_builds(self) -> None:
        data = _full_data()
        for key in ("notes", "startDateLT", "endDateLT"):
            data.pop(key, None)
        result = build_create_handover_payload(data)
        assert isinstance(result, dict)


# ===========================================================================
# TestBuildCreateHandoverPayloadValidation
# ===========================================================================


class TestBuildCreateHandoverPayloadValidation:
    def test_raises_value_error_on_empty_data(self) -> None:
        with pytest.raises(ValueError):
            build_create_handover_payload({})

    def test_raises_value_error_when_mall_missing(self) -> None:
        data = _full_data()
        del data["mall"]
        with pytest.raises(ValueError, match="mall"):
            build_create_handover_payload(data)

    def test_raises_value_error_when_title_empty_string(self) -> None:
        data = _full_data()
        data["title"] = ""
        with pytest.raises(ValueError, match="title"):
            build_create_handover_payload(data)

    def test_raises_value_error_when_unit_codes_empty_list(self) -> None:
        data = _full_data()
        data["unit_codes"] = []
        with pytest.raises(ValueError, match="unit_codes"):
            build_create_handover_payload(data)

    def test_raises_value_error_when_lease_id_none(self) -> None:
        data = _full_data()
        data["lease_id"] = None
        with pytest.raises(ValueError, match="lease_id"):
            build_create_handover_payload(data)

    def test_error_message_lists_missing_keys(self) -> None:
        data = _full_data()
        del data["brand"]
        del data["city"]
        with pytest.raises(ValueError) as exc_info:
            build_create_handover_payload(data)
        msg = str(exc_info.value)
        assert "brand" in msg
        assert "city" in msg

    @pytest.mark.parametrize("key", sorted(_REQUIRED_DATA_KEYS))
    def test_each_required_key_triggers_error_when_missing(self, key: str) -> None:
        data = _full_data()
        del data[key]
        with pytest.raises(ValueError):
            build_create_handover_payload(data)

    def test_integer_zero_contracted_area_does_not_raise(self) -> None:
        """contracted_area = 0 is valid — must not be treated as missing."""
        data = _full_data()
        data["contracted_area"] = 0
        result = build_create_handover_payload(data)
        assert result["payload"]["contracted_area"] == 0

    def test_false_value_does_not_raise(self) -> None:
        """False is a valid value — must not be treated as missing."""
        data = _full_data()
        data["contracted_area"] = False
        result = build_create_handover_payload(data)
        assert result["payload"]["contracted_area"] is False


# ===========================================================================
# TestBuildCreateHandoverPayloadConstants
# ===========================================================================


class TestBuildCreateHandoverPayloadConstants:
    def test_service_category_is_fit_out_and_handover(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["service_category"] == "FIT_OUT_AND_HANDOVER"

    def test_sub_category_is_handover(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["sub_category"] == "HANDOVER"

    def test_service_request_id_is_empty_for_new_creation(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["service_request_id"] == ""

    def test_attachments_always_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["attachments"] == ""

    def test_guideline_link_always_empty_string(self) -> None:
        result = build_create_handover_payload(_full_data())
        assert result["payload"]["guideLineLink"] == ""


# ===========================================================================
# TestPayloadBuilderServiceClass
# ===========================================================================


class TestPayloadBuilderServiceClass:
    _svc = PayloadBuilderService()

    def test_build_returns_dict_copy(self) -> None:
        draft = {"key": "value"}
        result = self._svc.build(draft)
        assert result == draft
        assert result is not draft

    def test_build_create_handover_payload_delegates(self) -> None:
        data = _full_data()
        result = self._svc.build_create_handover_payload(data)
        assert result == build_create_handover_payload(data)

    def test_build_create_handover_payload_raises_on_missing(self) -> None:
        with pytest.raises(ValueError):
            self._svc.build_create_handover_payload({})


# ===========================================================================
# TestPayloadBuilderNodeIntegration
# ===========================================================================


class TestPayloadBuilderNodeIntegration:
    @pytest.mark.asyncio
    async def test_node_stores_payload_in_backend_refs(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {
            "collected_data": _full_data(),
            "workflow_stage": "CREATE_SR",
        }
        result = await payload_builder_node(state)
        assert "backend_refs" in result
        assert "create_payload" in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_node_payload_has_correct_structure(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {
            "collected_data": _full_data(),
            "workflow_stage": "CREATE_SR",
        }
        result = await payload_builder_node(state)
        create_payload = result["backend_refs"]["create_payload"]
        assert "payload" in create_payload
        assert create_payload["service_category"] == "FIT_OUT_AND_HANDOVER"
        assert create_payload["sub_category"] == "HANDOVER"
        assert create_payload["service_request_id"] == ""

    @pytest.mark.asyncio
    async def test_node_returns_failed_status_on_missing_keys(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {
            "collected_data": {},
            "workflow_stage": "CREATE_SR",
        }
        result = await payload_builder_node(state)
        assert result.get("status") == "FAILED"

    @pytest.mark.asyncio
    async def test_node_skips_non_create_sr_stages(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {
            "collected_data": _full_data(),
            "workflow_stage": "FM_REVIEW",
        }
        result = await payload_builder_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_node_preserves_existing_backend_refs(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {
            "collected_data": _full_data(),
            "workflow_stage": "CREATE_SR",
            "backend_refs": {"existing_key": "existing_value"},
        }
        result = await payload_builder_node(state)
        assert result["backend_refs"]["existing_key"] == "existing_value"
        assert "create_payload" in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_node_defaults_to_create_sr_when_stage_absent(self) -> None:
        from app.agents.graph.nodes.payload_builder_node import payload_builder_node

        state: dict[str, Any] = {"collected_data": _full_data()}
        result = await payload_builder_node(state)
        assert "backend_refs" in result
        assert "create_payload" in result["backend_refs"]
