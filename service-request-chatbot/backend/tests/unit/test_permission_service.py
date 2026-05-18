"""Unit tests for app.agents.services.permission_service.

Coverage
--------
- User with the required role passes each action
- User without the required role raises PermissionDeniedError
- Both FM_APPROVAL and RDD_FINAL_APPROVAL share CAN_APPROVE_HANDOVER_SR
- Unknown / unmapped action is fail-open (no error)
- PermissionDeniedError carries the correct action and required_role attributes
"""

from __future__ import annotations

import pytest

from app.agents.services.permission_service import (
    ACTION_PERMISSION_MAP,
    PermissionDeniedError,
    PermissionService,
)
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(*roles: str) -> AuthContext:
    return AuthContext(subject_id="test-user", tenant_id=None, roles=frozenset(roles))


_EMPTY_AUTH = _auth()  # no roles at all
_svc = PermissionService()


# ---------------------------------------------------------------------------
# ACTION_PERMISSION_MAP shape
# ---------------------------------------------------------------------------


class TestPermissionMapShape:
    def test_all_expected_actions_are_present(self) -> None:
        expected = {
            "CREATE_HANDOVER_SR",
            "FM_APPROVAL",
            "RDD_FINAL_APPROVAL",
            "VIEW_HANDOVER_SR",
        }
        assert expected.issubset(ACTION_PERMISSION_MAP.keys())

    def test_create_requires_can_raise(self) -> None:
        assert ACTION_PERMISSION_MAP["CREATE_HANDOVER_SR"] == "CAN_RAISE_HANDOVER_SR"

    def test_fm_approval_requires_can_approve(self) -> None:
        assert ACTION_PERMISSION_MAP["FM_APPROVAL"] == "CAN_APPROVE_HANDOVER_SR"

    def test_rdd_approval_requires_can_approve(self) -> None:
        assert ACTION_PERMISSION_MAP["RDD_FINAL_APPROVAL"] == "CAN_APPROVE_HANDOVER_SR"

    def test_view_requires_view_permission(self) -> None:
        assert ACTION_PERMISSION_MAP["VIEW_HANDOVER_SR"] == "VIEW_FIT_OUT_HANDOVER"


# ---------------------------------------------------------------------------
# check() — pass cases
# ---------------------------------------------------------------------------


class TestCheckPass:
    def test_create_handover_sr_with_correct_role(self) -> None:
        auth = _auth("CAN_RAISE_HANDOVER_SR")
        _svc.check("CREATE_HANDOVER_SR", auth)  # must not raise

    def test_fm_approval_with_correct_role(self) -> None:
        auth = _auth("CAN_APPROVE_HANDOVER_SR")
        _svc.check("FM_APPROVAL", auth)

    def test_rdd_final_approval_with_correct_role(self) -> None:
        auth = _auth("CAN_APPROVE_HANDOVER_SR")
        _svc.check("RDD_FINAL_APPROVAL", auth)

    def test_view_handover_sr_with_correct_role(self) -> None:
        auth = _auth("VIEW_FIT_OUT_HANDOVER")
        _svc.check("VIEW_HANDOVER_SR", auth)

    def test_user_with_extra_roles_also_passes(self) -> None:
        """Having additional unrelated roles must not block access."""
        auth = _auth("CAN_RAISE_HANDOVER_SR", "SOME_OTHER_ROLE", "ADMIN")
        _svc.check("CREATE_HANDOVER_SR", auth)

    def test_unknown_action_is_fail_open(self) -> None:
        """An action not in the map must silently pass (fail-open for POC)."""
        _svc.check("UNMAPPED_ACTION_XYZ", _EMPTY_AUTH)


# ---------------------------------------------------------------------------
# check() — deny cases
# ---------------------------------------------------------------------------


class TestCheckDeny:
    def test_empty_roles_denied_for_create(self) -> None:
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("CREATE_HANDOVER_SR", _EMPTY_AUTH)
        err = exc_info.value
        assert err.action == "CREATE_HANDOVER_SR"
        assert err.required_role == "CAN_RAISE_HANDOVER_SR"

    def test_wrong_role_denied_for_create(self) -> None:
        auth = _auth("VIEW_FIT_OUT_HANDOVER")  # has view but not create
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("CREATE_HANDOVER_SR", auth)
        assert exc_info.value.required_role == "CAN_RAISE_HANDOVER_SR"

    def test_empty_roles_denied_for_fm_approval(self) -> None:
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("FM_APPROVAL", _EMPTY_AUTH)
        assert exc_info.value.required_role == "CAN_APPROVE_HANDOVER_SR"

    def test_empty_roles_denied_for_rdd_approval(self) -> None:
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("RDD_FINAL_APPROVAL", _EMPTY_AUTH)
        assert exc_info.value.required_role == "CAN_APPROVE_HANDOVER_SR"

    def test_create_role_cannot_approve(self) -> None:
        """CAN_RAISE_HANDOVER_SR does not grant approval rights."""
        auth = _auth("CAN_RAISE_HANDOVER_SR")
        with pytest.raises(PermissionDeniedError):
            _svc.check("FM_APPROVAL", auth)

    def test_error_message_is_descriptive(self) -> None:
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("VIEW_HANDOVER_SR", _EMPTY_AUTH)
        msg = str(exc_info.value)
        assert "VIEW_HANDOVER_SR" in msg
        assert "VIEW_FIT_OUT_HANDOVER" in msg


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


class TestConvenienceWrappers:
    def test_ensure_can_create_request_passes(self) -> None:
        auth = _auth("CAN_RAISE_HANDOVER_SR")
        _svc.ensure_can_create_request(auth)  # no exception

    def test_ensure_can_create_request_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_create_request(_EMPTY_AUTH)

    def test_ensure_can_approve_fm(self) -> None:
        auth = _auth("CAN_APPROVE_HANDOVER_SR")
        _svc.ensure_can_approve_request("FM_APPROVAL", auth)

    def test_ensure_can_approve_rdd(self) -> None:
        auth = _auth("CAN_APPROVE_HANDOVER_SR")
        _svc.ensure_can_approve_request("RDD_FINAL_APPROVAL", auth)

    def test_ensure_can_approve_raises_without_role(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_approve_request("FM_APPROVAL", _EMPTY_AUTH)

    def test_ensure_can_view_trace_passes(self) -> None:
        auth = _auth("VIEW_FIT_OUT_HANDOVER")
        _svc.ensure_can_view_trace(auth)

    def test_ensure_can_view_trace_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_view_trace(_EMPTY_AUTH)


# ---------------------------------------------------------------------------
# PermissionDeniedError attributes
# ---------------------------------------------------------------------------


class TestPermissionDeniedError:
    def test_error_has_action_and_required_role(self) -> None:
        err = PermissionDeniedError(action="FM_APPROVAL", required_role="CAN_APPROVE_HANDOVER_SR")
        assert err.action == "FM_APPROVAL"
        assert err.required_role == "CAN_APPROVE_HANDOVER_SR"

    def test_error_is_exception_subclass(self) -> None:
        err = PermissionDeniedError("X", "Y")
        assert isinstance(err, Exception)

    def test_str_contains_both_fields(self) -> None:
        err = PermissionDeniedError("CREATE_HANDOVER_SR", "CAN_RAISE_HANDOVER_SR")
        msg = str(err)
        assert "CREATE_HANDOVER_SR" in msg
        assert "CAN_RAISE_HANDOVER_SR" in msg
