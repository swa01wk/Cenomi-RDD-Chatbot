"""Unit tests for ROLE_PERMISSION_MAP and _build_auth_context.

Coverage
--------
- ROLE_PERMISSION_MAP shape: 4 roles, correct permission sets
- APPROVE_RDD_FINAL in ACTION_PERMISSION_MAP
- _build_auth_context: derives AuthContext from role string
- Cross-role permission denials (FM cannot do RDD, DD cannot do FM, etc.)
- permission_service.check() with role-derived AuthContext
"""

from __future__ import annotations

import pytest

from app.agents.services.permission_service import (
    ACTION_PERMISSION_MAP,
    ROLE_PERMISSION_MAP,
    PermissionDeniedError,
    PermissionService,
)
from app.services.chat_orchestration_service import _build_auth_context
from app.types.chat import AuthContext


_svc = PermissionService()


# ---------------------------------------------------------------------------
# ROLE_PERMISSION_MAP shape
# ---------------------------------------------------------------------------


class TestRolePermissionMapShape:
    def test_map_has_exactly_four_roles(self) -> None:
        assert set(ROLE_PERMISSION_MAP.keys()) == {
            "MALL_MANAGER",
            "FM_MANAGER",
            "OPERATIONS",
            "DD_ENGINEER",
        }

    def test_all_values_are_frozensets(self) -> None:
        for role, perms in ROLE_PERMISSION_MAP.items():
            assert isinstance(perms, frozenset), f"{role} value should be frozenset"

    def test_mall_manager_can_raise_sr(self) -> None:
        assert "CAN_RAISE_HANDOVER_SR" in ROLE_PERMISSION_MAP["MALL_MANAGER"]

    def test_mall_manager_cannot_review(self) -> None:
        perms = ROLE_PERMISSION_MAP["MALL_MANAGER"]
        assert "CAN_FM_REVIEW_HANDOVER_SR" not in perms
        assert "CAN_RDD_REVIEW_HANDOVER_SR" not in perms

    def test_fm_manager_has_fm_review_and_approve(self) -> None:
        perms = ROLE_PERMISSION_MAP["FM_MANAGER"]
        assert "CAN_FM_REVIEW_HANDOVER_SR" in perms
        assert "CAN_APPROVE_FM_HANDOVER_SR" in perms

    def test_fm_manager_cannot_rdd_review(self) -> None:
        assert "CAN_RDD_REVIEW_HANDOVER_SR" not in ROLE_PERMISSION_MAP["FM_MANAGER"]

    def test_operations_same_as_fm_manager(self) -> None:
        assert ROLE_PERMISSION_MAP["OPERATIONS"] == ROLE_PERMISSION_MAP["FM_MANAGER"]

    def test_dd_engineer_has_rdd_review(self) -> None:
        assert "CAN_RDD_REVIEW_HANDOVER_SR" in ROLE_PERMISSION_MAP["DD_ENGINEER"]

    def test_dd_engineer_cannot_fm_review(self) -> None:
        perms = ROLE_PERMISSION_MAP["DD_ENGINEER"]
        assert "CAN_FM_REVIEW_HANDOVER_SR" not in perms
        assert "CAN_APPROVE_FM_HANDOVER_SR" not in perms

    def test_dd_engineer_cannot_raise_sr(self) -> None:
        assert "CAN_RAISE_HANDOVER_SR" not in ROLE_PERMISSION_MAP["DD_ENGINEER"]

    def test_all_roles_have_view_permission(self) -> None:
        for role, perms in ROLE_PERMISSION_MAP.items():
            assert "VIEW_FIT_OUT_HANDOVER" in perms, f"{role} missing VIEW_FIT_OUT_HANDOVER"


# ---------------------------------------------------------------------------
# APPROVE_RDD_FINAL in ACTION_PERMISSION_MAP
# ---------------------------------------------------------------------------


class TestApproveRddFinalAction:
    def test_action_exists_in_map(self) -> None:
        assert "APPROVE_RDD_FINAL" in ACTION_PERMISSION_MAP

    def test_action_requires_rdd_review_permission(self) -> None:
        assert ACTION_PERMISSION_MAP["APPROVE_RDD_FINAL"] == "CAN_RDD_REVIEW_HANDOVER_SR"

    def test_dd_engineer_can_approve_rdd_final(self) -> None:
        auth = AuthContext(
            subject_id="dd_user",
            tenant_id=None,
            roles=ROLE_PERMISSION_MAP["DD_ENGINEER"],
        )
        _svc.check("APPROVE_RDD_FINAL", auth)  # must not raise

    def test_fm_manager_cannot_approve_rdd_final(self) -> None:
        auth = AuthContext(
            subject_id="fm_user",
            tenant_id=None,
            roles=ROLE_PERMISSION_MAP["FM_MANAGER"],
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("APPROVE_RDD_FINAL", auth)
        assert exc_info.value.required_role == "CAN_RDD_REVIEW_HANDOVER_SR"

    def test_mall_manager_cannot_approve_rdd_final(self) -> None:
        auth = AuthContext(
            subject_id="mm_user",
            tenant_id=None,
            roles=ROLE_PERMISSION_MAP["MALL_MANAGER"],
        )
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_RDD_FINAL", auth)

    def test_empty_roles_cannot_approve_rdd_final(self) -> None:
        auth = AuthContext(subject_id="anon", tenant_id=None, roles=frozenset())
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_RDD_FINAL", auth)


# ---------------------------------------------------------------------------
# _build_auth_context helper
# ---------------------------------------------------------------------------


class TestBuildAuthContext:
    def test_returns_auth_context_instance(self) -> None:
        result = _build_auth_context("FM_MANAGER")
        assert isinstance(result, AuthContext)

    def test_fm_manager_role_produces_fm_permissions(self) -> None:
        auth = _build_auth_context("FM_MANAGER")
        assert "CAN_FM_REVIEW_HANDOVER_SR" in auth.roles
        assert "CAN_APPROVE_FM_HANDOVER_SR" in auth.roles

    def test_dd_engineer_role_produces_rdd_permissions(self) -> None:
        auth = _build_auth_context("DD_ENGINEER")
        assert "CAN_RDD_REVIEW_HANDOVER_SR" in auth.roles

    def test_mall_manager_role_produces_create_permission(self) -> None:
        auth = _build_auth_context("MALL_MANAGER")
        assert "CAN_RAISE_HANDOVER_SR" in auth.roles

    def test_none_role_produces_empty_roles(self) -> None:
        auth = _build_auth_context(None)
        assert len(auth.roles) == 0

    def test_unknown_role_produces_empty_roles(self) -> None:
        auth = _build_auth_context("SUPER_ADMIN")
        assert len(auth.roles) == 0

    def test_subject_id_is_chat_user(self) -> None:
        auth = _build_auth_context("FM_MANAGER")
        assert auth.subject_id == "chat_user"

    def test_tenant_id_is_none(self) -> None:
        auth = _build_auth_context("FM_MANAGER")
        assert auth.tenant_id is None


# ---------------------------------------------------------------------------
# Cross-role permission denials via check()
# ---------------------------------------------------------------------------


class TestCrossRoleDenials:
    def test_fm_manager_cannot_raise_sr(self) -> None:
        auth = _build_auth_context("FM_MANAGER")
        with pytest.raises(PermissionDeniedError):
            _svc.check("CREATE_HANDOVER_SR", auth)

    def test_dd_engineer_cannot_approve_fm(self) -> None:
        auth = _build_auth_context("DD_ENGINEER")
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_FM_HANDOVER", auth)

    def test_mall_manager_cannot_save_fm_progress(self) -> None:
        auth = _build_auth_context("MALL_MANAGER")
        with pytest.raises(PermissionDeniedError):
            _svc.check("SAVE_FM_HANDOVER_PROGRESS", auth)

    def test_operations_can_perform_fm_actions(self) -> None:
        auth = _build_auth_context("OPERATIONS")
        _svc.check("SAVE_FM_HANDOVER_PROGRESS", auth)  # must not raise
        _svc.check("APPROVE_FM_HANDOVER", auth)  # must not raise

    def test_operations_cannot_rdd_review(self) -> None:
        auth = _build_auth_context("OPERATIONS")
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_RDD_FINAL", auth)

    def test_permission_denied_error_contains_action_name(self) -> None:
        auth = _build_auth_context("MALL_MANAGER")
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("APPROVE_RDD_FINAL", auth)
        assert "APPROVE_RDD_FINAL" in str(exc_info.value)
