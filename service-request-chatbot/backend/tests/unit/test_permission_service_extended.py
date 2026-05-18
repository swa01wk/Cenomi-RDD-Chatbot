"""Extended unit tests for permission_service — new action mappings.

Coverage (extends test_permission_service.py)
---------------------------------------------
- All 6 new action mappings are enforced
- Unknown action is now fail-CLOSED (UNKNOWN_ACTION required_role)
- ensure_can_fm_review / ensure_can_approve_fm / ensure_can_rdd_review wrappers
- Role-specific checks (FM roles cannot submit RDD; RDD role cannot approve FM)
"""

from __future__ import annotations

import pytest

from app.agents.services.permission_service import (
    ACTION_PERMISSION_MAP,
    PermissionDeniedError,
    PermissionService,
)
from app.types.chat import AuthContext


def _auth(*roles: str) -> AuthContext:
    return AuthContext(subject_id="test-user", tenant_id=None, roles=frozenset(roles))


_EMPTY_AUTH = _auth()
_svc = PermissionService()


# ---------------------------------------------------------------------------
# New action mappings
# ---------------------------------------------------------------------------


class TestNewActionMappings:
    def test_upload_fm_document_maps_to_can_fm_review(self) -> None:
        assert ACTION_PERMISSION_MAP["UPLOAD_FM_HANDOVER_DOCUMENT"] == "CAN_FM_REVIEW_HANDOVER_SR"

    def test_save_fm_progress_maps_to_can_fm_review(self) -> None:
        assert ACTION_PERMISSION_MAP["SAVE_FM_HANDOVER_PROGRESS"] == "CAN_FM_REVIEW_HANDOVER_SR"

    def test_approve_fm_maps_to_can_approve_fm(self) -> None:
        assert ACTION_PERMISSION_MAP["APPROVE_FM_HANDOVER"] == "CAN_APPROVE_FM_HANDOVER_SR"

    def test_reject_fm_maps_to_can_approve_fm(self) -> None:
        assert ACTION_PERMISSION_MAP["REJECT_FM_HANDOVER"] == "CAN_APPROVE_FM_HANDOVER_SR"

    def test_upload_rdd_maps_to_can_rdd_review(self) -> None:
        assert ACTION_PERMISSION_MAP["UPLOAD_RDD_HANDOVER_REPORT"] == "CAN_RDD_REVIEW_HANDOVER_SR"

    def test_submit_rdd_maps_to_can_rdd_review(self) -> None:
        assert ACTION_PERMISSION_MAP["SUBMIT_RDD_HANDOVER_REPORT"] == "CAN_RDD_REVIEW_HANDOVER_SR"


# ---------------------------------------------------------------------------
# Fail-closed behaviour for unknown actions
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_completely_unknown_action_raises(self) -> None:
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("TOTALLY_UNKNOWN_ACTION_XYZ", _EMPTY_AUTH)
        assert exc_info.value.required_role == "UNKNOWN_ACTION"

    def test_unknown_action_also_denied_when_user_has_all_roles(self) -> None:
        auth = _auth(
            "CAN_RAISE_HANDOVER_SR",
            "CAN_FM_REVIEW_HANDOVER_SR",
            "CAN_RDD_REVIEW_HANDOVER_SR",
            "CAN_APPROVE_FM_HANDOVER_SR",
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            _svc.check("COMPLETELY_UNKNOWN", auth)
        assert exc_info.value.required_role == "UNKNOWN_ACTION"


# ---------------------------------------------------------------------------
# Role-specific enforcement
# ---------------------------------------------------------------------------


class TestRoleSpecificEnforcement:
    def test_fm_review_role_can_save_progress(self) -> None:
        auth = _auth("CAN_FM_REVIEW_HANDOVER_SR")
        _svc.check("SAVE_FM_HANDOVER_PROGRESS", auth)  # must not raise

    def test_fm_review_role_can_upload_fm_doc(self) -> None:
        auth = _auth("CAN_FM_REVIEW_HANDOVER_SR")
        _svc.check("UPLOAD_FM_HANDOVER_DOCUMENT", auth)

    def test_fm_review_role_cannot_approve_fm(self) -> None:
        auth = _auth("CAN_FM_REVIEW_HANDOVER_SR")  # can review but NOT approve
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_FM_HANDOVER", auth)

    def test_fm_approve_role_can_approve(self) -> None:
        auth = _auth("CAN_APPROVE_FM_HANDOVER_SR")
        _svc.check("APPROVE_FM_HANDOVER", auth)

    def test_rdd_engineer_can_submit_report(self) -> None:
        auth = _auth("CAN_RDD_REVIEW_HANDOVER_SR")
        _svc.check("SUBMIT_RDD_HANDOVER_REPORT", auth)

    def test_rdd_engineer_can_upload_report(self) -> None:
        auth = _auth("CAN_RDD_REVIEW_HANDOVER_SR")
        _svc.check("UPLOAD_RDD_HANDOVER_REPORT", auth)

    def test_rdd_engineer_cannot_approve_fm(self) -> None:
        auth = _auth("CAN_RDD_REVIEW_HANDOVER_SR")
        with pytest.raises(PermissionDeniedError):
            _svc.check("APPROVE_FM_HANDOVER", auth)

    def test_mall_manager_cannot_do_fm_review(self) -> None:
        auth = _auth("CAN_RAISE_HANDOVER_SR")
        with pytest.raises(PermissionDeniedError):
            _svc.check("SAVE_FM_HANDOVER_PROGRESS", auth)

    def test_mall_manager_cannot_do_rdd_review(self) -> None:
        auth = _auth("CAN_RAISE_HANDOVER_SR")
        with pytest.raises(PermissionDeniedError):
            _svc.check("SUBMIT_RDD_HANDOVER_REPORT", auth)


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


class TestNewConvenienceWrappers:
    def test_ensure_can_fm_review_passes(self) -> None:
        auth = _auth("CAN_FM_REVIEW_HANDOVER_SR")
        _svc.ensure_can_fm_review(auth)

    def test_ensure_can_fm_review_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_fm_review(_EMPTY_AUTH)

    def test_ensure_can_approve_fm_passes(self) -> None:
        auth = _auth("CAN_APPROVE_FM_HANDOVER_SR")
        _svc.ensure_can_approve_fm(auth)

    def test_ensure_can_approve_fm_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_approve_fm(_EMPTY_AUTH)

    def test_ensure_can_rdd_review_passes(self) -> None:
        auth = _auth("CAN_RDD_REVIEW_HANDOVER_SR")
        _svc.ensure_can_rdd_review(auth)

    def test_ensure_can_rdd_review_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            _svc.ensure_can_rdd_review(_EMPTY_AUTH)
