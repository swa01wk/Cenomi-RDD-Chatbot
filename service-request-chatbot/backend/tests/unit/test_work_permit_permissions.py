"""Unit tests — Work Permit permission integration.

Test groups
-----------
TestWorkPermitActionMap        — CREATE_WORK_PERMIT_SR and VIEW_WORK_PERMIT_SR
                                 are present in ACTION_PERMISSION_MAP.
TestWorkPermitRoleMap          — MALL_MANAGER has CAN_RAISE_WORK_PERMIT_SR;
                                 other roles have VIEW_WORK_PERMIT but not CREATE.
TestPermissionServiceWP        — PermissionService.check() enforces WP actions.
TestWorkPermitValidation       — ValidationService handles CREATE_WORK_PERMIT stage.
TestWorkPermitSubmissionGuard  — work_permit_api_submission_node permission check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.services.permission_service import (
    ACTION_PERMISSION_MAP,
    ROLE_PERMISSION_MAP,
    PermissionDeniedError,
    PermissionService,
)
from app.agents.services.validation_service import ValidationService
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _auth(role: str) -> AuthContext:
    """Build an AuthContext for a given role using the role's permission set."""
    return AuthContext(
        subject_id=f"{role.lower()}-uuid",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP.get(role, frozenset()),
    )


# ===========================================================================
# TestWorkPermitActionMap
# ===========================================================================


class TestWorkPermitActionMap:
    """Work Permit actions must be registered in ACTION_PERMISSION_MAP."""

    def test_create_work_permit_sr_is_mapped(self) -> None:
        assert "CREATE_WORK_PERMIT_SR" in ACTION_PERMISSION_MAP

    def test_view_work_permit_sr_is_mapped(self) -> None:
        assert "VIEW_WORK_PERMIT_SR" in ACTION_PERMISSION_MAP

    def test_create_work_permit_maps_to_can_raise(self) -> None:
        assert ACTION_PERMISSION_MAP["CREATE_WORK_PERMIT_SR"] == "CAN_RAISE_WORK_PERMIT_SR"

    def test_view_work_permit_maps_to_view_permission(self) -> None:
        assert ACTION_PERMISSION_MAP["VIEW_WORK_PERMIT_SR"] == "VIEW_WORK_PERMIT"


# ===========================================================================
# TestWorkPermitRoleMap
# ===========================================================================


class TestWorkPermitRoleMap:
    """Role permission map must include Work Permit permissions for correct roles."""

    def test_mall_manager_can_raise_wp(self) -> None:
        assert "CAN_RAISE_WORK_PERMIT_SR" in ROLE_PERMISSION_MAP["MALL_MANAGER"]

    def test_mall_manager_can_view_wp(self) -> None:
        assert "VIEW_WORK_PERMIT" in ROLE_PERMISSION_MAP["MALL_MANAGER"]

    def test_fm_manager_cannot_raise_wp(self) -> None:
        assert "CAN_RAISE_WORK_PERMIT_SR" not in ROLE_PERMISSION_MAP.get("FM_MANAGER", frozenset())

    def test_dd_engineer_cannot_raise_wp(self) -> None:
        assert "CAN_RAISE_WORK_PERMIT_SR" not in ROLE_PERMISSION_MAP.get("DD_ENGINEER", frozenset())

    def test_operations_cannot_raise_wp(self) -> None:
        assert "CAN_RAISE_WORK_PERMIT_SR" not in ROLE_PERMISSION_MAP.get("OPERATIONS", frozenset())

    def test_fm_manager_can_view_wp(self) -> None:
        assert "VIEW_WORK_PERMIT" in ROLE_PERMISSION_MAP.get("FM_MANAGER", frozenset())

    def test_dd_engineer_can_view_wp(self) -> None:
        assert "VIEW_WORK_PERMIT" in ROLE_PERMISSION_MAP.get("DD_ENGINEER", frozenset())

    def test_admin_can_raise_wp(self) -> None:
        assert "CAN_RAISE_WORK_PERMIT_SR" in ROLE_PERMISSION_MAP.get("ADMIN", frozenset())


# ===========================================================================
# TestPermissionServiceWP
# ===========================================================================


class TestPermissionServiceWP:
    """PermissionService.check() and convenience methods for Work Permit."""

    def test_mall_manager_can_create_wp(self) -> None:
        svc = PermissionService()
        svc.check("CREATE_WORK_PERMIT_SR", _auth("MALL_MANAGER"))  # should not raise

    def test_fm_manager_cannot_create_wp(self) -> None:
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError):
            svc.check("CREATE_WORK_PERMIT_SR", _auth("FM_MANAGER"))

    def test_dd_engineer_cannot_create_wp(self) -> None:
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError):
            svc.check("CREATE_WORK_PERMIT_SR", _auth("DD_ENGINEER"))

    def test_operations_cannot_create_wp(self) -> None:
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError):
            svc.check("CREATE_WORK_PERMIT_SR", _auth("OPERATIONS"))

    def test_all_roles_can_view_wp(self) -> None:
        svc = PermissionService()
        for role in ("MALL_MANAGER", "FM_MANAGER", "OPERATIONS", "DD_ENGINEER"):
            svc.check("VIEW_WORK_PERMIT_SR", _auth(role))  # must not raise

    def test_ensure_can_create_work_permit_mm(self) -> None:
        svc = PermissionService()
        svc.ensure_can_create_work_permit(_auth("MALL_MANAGER"))

    def test_ensure_can_create_work_permit_denied_for_fm(self) -> None:
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError):
            svc.ensure_can_create_work_permit(_auth("FM_MANAGER"))

    def test_permission_denied_error_is_fail_closed(self) -> None:
        """Unknown WP action must raise PermissionDeniedError — fail-closed."""
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError) as exc_info:
            svc.check("UNKNOWN_WP_ACTION", _auth("MALL_MANAGER"))
        assert exc_info.value.required_role == "UNKNOWN_ACTION"

    def test_permission_denied_error_has_action_attribute(self) -> None:
        svc = PermissionService()
        with pytest.raises(PermissionDeniedError) as exc_info:
            svc.check("CREATE_WORK_PERMIT_SR", _auth("FM_MANAGER"))
        assert exc_info.value.action == "CREATE_WORK_PERMIT_SR"


# ===========================================================================
# TestWorkPermitValidation
# ===========================================================================


class TestWorkPermitValidation:
    """ValidationService handles CREATE_WORK_PERMIT stage correctly."""

    def _complete_wp_data(self) -> dict[str, Any]:
        return {
            "lease_code": "t0105712",
            "lease_id": 456,
            "property_id": 789,
            "unit_codes": ["FF050"],
            "mall": "Jawharat Jeddah",
            "brand": "Brand Under Armour",
            "work_permit_type": "CONSTRUCTION_COLD",
            "description": "Cold work construction permit",
            "start_date": "2026-08-01",
            "end_date": "2026-08-05",
            "contractor_name": "ABC Contractors",
            "comments": "",
        }

    def test_complete_wp_data_no_errors(self) -> None:
        svc = ValidationService()
        errors = svc.validate_draft(self._complete_wp_data(), workflow_stage="CREATE_WORK_PERMIT")
        assert len(errors) == 0

    def test_missing_work_permit_type_is_error(self) -> None:
        svc = ValidationService()
        data = self._complete_wp_data()
        del data["work_permit_type"]
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
        type_errors = [e for e in errors if e["field"] == "work_permit_type"]
        assert len(type_errors) >= 1

    def test_invalid_work_permit_type_enum_is_error(self) -> None:
        svc = ValidationService()
        data = self._complete_wp_data()
        data["work_permit_type"] = "INVALID_TYPE"
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
        enum_errors = [e for e in errors if e["validation_type"] == "enum" and e["field"] == "work_permit_type"]
        assert len(enum_errors) == 1

    def test_valid_wp_types_all_pass_enum_check(self) -> None:
        svc = ValidationService()
        valid_types = [
            "CONSTRUCTION_HOT",
            "CONSTRUCTION_COLD",
            "CONSTRUCTION_ROOF_ACCESS",
            "MAINTENANCE_HOT",
            "MAINTENANCE_COLD",
            "MAINTENANCE_ROOF_ACCESS",
            "OPERATIONS",
        ]
        for wp_type in valid_types:
            data = self._complete_wp_data()
            data["work_permit_type"] = wp_type
            errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
            enum_errors = [e for e in errors if e["validation_type"] == "enum"]
            assert len(enum_errors) == 0, f"Unexpected enum error for type '{wp_type}'"

    def test_missing_required_field_lease_code(self) -> None:
        svc = ValidationService()
        data = self._complete_wp_data()
        del data["lease_code"]
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
        lc_errors = [e for e in errors if e["field"] == "lease_code"]
        assert len(lc_errors) >= 1

    def test_missing_description_is_error(self) -> None:
        svc = ValidationService()
        data = self._complete_wp_data()
        del data["description"]
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
        # description is in OPTIONAL_FIELDS for WP — None is missing, empty string is not
        desc_errors = [e for e in errors if e["field"] == "description"]
        assert len(desc_errors) >= 1

    def test_empty_string_description_is_acceptable(self) -> None:
        """Empty string description is valid for WP (OPTIONAL_FIELDS)."""
        svc = ValidationService()
        data = self._complete_wp_data()
        data["description"] = ""
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT")
        desc_errors = [e for e in errors if e["field"] == "description"]
        assert len(desc_errors) == 0

    def test_create_wp_no_document_count_requirement(self) -> None:
        svc = ValidationService()
        data = self._complete_wp_data()
        errors = svc.validate_draft(data, workflow_stage="CREATE_WORK_PERMIT", documents=[])
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 0


# ===========================================================================
# TestWorkPermitSubmissionGuard
# ===========================================================================


class TestWorkPermitSubmissionGuard:
    """work_permit_api_submission_node checks permissions before submission."""

    @pytest.mark.asyncio
    async def test_mall_manager_can_submit(self) -> None:
        from app.agents.graph.nodes.work_permit.work_permit_api_submission_node import (
            work_permit_api_submission_node,
        )

        mock_result = AsyncMock()
        mock_result.sr_id = "SR-WP-001"
        mock_result.error = None
        mock_result.correlation_id = "corr-001"
        mock_result.status_code = 201

        state: dict[str, Any] = {
            "confirmation_status": "CONFIRMED",
            "validation_errors": [],
            "backend_refs": {"create_payload": {"service_category": "WORK_PERMIT"}},
            "auth_context": _auth("MALL_MANAGER"),
        }

        with patch(
            "app.agents.graph.nodes.work_permit.work_permit_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.create_service_request.return_value = mock_result
            mock_svc_factory.return_value = mock_svc
            result = await work_permit_api_submission_node(state)

        assert result.get("status") != "FAILED" or "permission" not in result.get("response_message", "").lower()

    @pytest.mark.asyncio
    async def test_fm_manager_is_denied(self) -> None:
        from app.agents.graph.nodes.work_permit.work_permit_api_submission_node import (
            work_permit_api_submission_node,
        )

        state: dict[str, Any] = {
            "confirmation_status": "CONFIRMED",
            "validation_errors": [],
            "backend_refs": {"create_payload": {"service_category": "WORK_PERMIT"}},
            "auth_context": _auth("FM_MANAGER"),
        }

        result = await work_permit_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_dd_engineer_is_denied(self) -> None:
        from app.agents.graph.nodes.work_permit.work_permit_api_submission_node import (
            work_permit_api_submission_node,
        )

        state: dict[str, Any] = {
            "confirmation_status": "CONFIRMED",
            "validation_errors": [],
            "backend_refs": {"create_payload": {"service_category": "WORK_PERMIT"}},
            "auth_context": _auth("DD_ENGINEER"),
        }

        result = await work_permit_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_no_auth_context_allows_submission(self) -> None:
        """When auth_context is None (shadow mode), permission check is skipped."""
        from app.agents.graph.nodes.work_permit.work_permit_api_submission_node import (
            work_permit_api_submission_node,
        )

        mock_result = AsyncMock()
        mock_result.sr_id = "SR-WP-002"
        mock_result.error = None
        mock_result.correlation_id = None
        mock_result.status_code = 201

        state: dict[str, Any] = {
            "confirmation_status": "CONFIRMED",
            "validation_errors": [],
            "backend_refs": {"create_payload": {"service_category": "WORK_PERMIT"}},
            "auth_context": None,
        }

        with patch(
            "app.agents.graph.nodes.work_permit.work_permit_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.create_service_request.return_value = mock_result
            mock_svc_factory.return_value = mock_svc
            result = await work_permit_api_submission_node(state)

        # Should proceed to submit (not fail on permission)
        assert result.get("status") in ("SUBMITTED", "FAILED")
        if result["status"] == "FAILED":
            assert "permission" not in result.get("response_message", "").lower()
