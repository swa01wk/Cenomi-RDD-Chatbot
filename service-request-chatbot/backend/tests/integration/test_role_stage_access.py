"""Integration tests — role-to-stage access enforcement.

Each role may only enter and act on its permitted workflow stage.
Attempting to enter or submit at a stage that belongs to another role must
be denied at the **node boundary**, not just at the permission-service level.

Matrix tested
-------------
Role          | CREATE_SR | FM_REVIEW | RDD_REVIEW
MALL_MANAGER  |    PASS   |   DENY    |    DENY
FM_MANAGER    |    DENY   |   PASS    |    DENY
OPERATIONS    |    DENY   |   PASS    |    DENY
DD_ENGINEER   |    DENY   |   DENY    |    PASS

"PASS" = node falls through or returns success action.
"DENY" = node returns status=WAITING_FOR_USER with a denial message.

Also tests that OPERATIONS and FM_MANAGER are treated equivalently at the
FM_REVIEW stage (both are allowed).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph.nodes.handover.fm_review_entry_node import fm_review_entry_node
from app.agents.graph.nodes.handover.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.nodes.handover.rdd_review_entry_node import rdd_review_entry_node
from app.agents.services.service_request_api_service import ServiceRequestCreationResult
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_for(role: str) -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id=f"{role.lower()}_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP.get(role, frozenset()),
    )


def _fm_state(role: str, action: str = "save_fm_progress") -> dict[str, Any]:
    return {
        "session_id": "role-access-sess-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {},
        "backend_refs": {"user_role": role},
        "action_override": action,
        "workflow_stage": "FM_REVIEW",
        "auth": _auth_for(role),
    }


def _rdd_entry_state(role: str, action: str = "submit_rdd_report") -> dict[str, Any]:
    return {
        "session_id": "role-access-sess-002",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {},
        "backend_refs": {"user_role": role},
        "action_override": action,
        "workflow_stage": "RDD_REVIEW",
        "auth": _auth_for(role),
    }


def _rdd_submit_api_state(role: str) -> dict[str, Any]:
    return {
        "session_id": "role-access-sess-003",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {},
        "backend_refs": {
            "user_role": role,
            "rdd_action": "submit",
            "sr_id": "sr-role-test-001",
            "rdd_payload": {"status": "REPORT_SUBMITTED"},
            "rdd_document_id": "doc-rdd-001",
        },
        "workflow_stage": "RDD_REVIEW",
        "auth": _auth_for(role),
    }


def _rdd_final_approve_api_state(role: str) -> dict[str, Any]:
    return {
        "session_id": "role-access-sess-004",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {},
        "backend_refs": {
            "user_role": role,
            "rdd_action": "final_approve",
            "sr_id": "sr-role-test-001",
            "rdd_payload": {
                "status": "APPROVED",
                "payload": {"current_sr_status": "REPORT_SUBMITTED"},
            },
        },
        "workflow_stage": "RDD_REVIEW",
        "auth": _auth_for(role),
    }


def _mock_patch_success() -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id="sr-role-test-001",
        endpoint="mock://service-requests/sr-role-test-001",
        request_payload={},
        response_payload={"success": True, "id": "sr-role-test-001"},
        latency_ms=5,
        status_code=200,
    )


# ---------------------------------------------------------------------------
# FM_REVIEW entry node — role access matrix
# ---------------------------------------------------------------------------


class TestFMReviewEntryRoleAccess:
    """fm_review_entry_node must allow FM_MANAGER and OPERATIONS; deny all others."""

    @pytest.mark.asyncio
    async def test_fm_manager_allowed(self) -> None:
        state = _fm_state("FM_MANAGER")
        result = await fm_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("fm_action") == "save_progress"

    @pytest.mark.asyncio
    async def test_operations_allowed(self) -> None:
        state = _fm_state("OPERATIONS")
        result = await fm_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("fm_action") == "save_progress"

    @pytest.mark.asyncio
    async def test_mall_manager_denied(self) -> None:
        state = _fm_state("MALL_MANAGER")
        result = await fm_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert "permission" in result["response_message"].lower() or "fm" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_dd_engineer_denied_from_fm_entry(self) -> None:
        state = _fm_state("DD_ENGINEER")
        result = await fm_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_unknown_role_denied(self) -> None:
        state = _fm_state("UNKNOWN_ROLE")
        result = await fm_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_operations_can_approve_fm(self) -> None:
        """OPERATIONS must be able to trigger approve_fm_review, same as FM_MANAGER."""
        state = _fm_state("OPERATIONS", action="approve_fm_review")
        result = await fm_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("fm_action") == "approve"

    @pytest.mark.asyncio
    async def test_fm_manager_can_approve_fm(self) -> None:
        state = _fm_state("FM_MANAGER", action="approve_fm_review")
        result = await fm_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("fm_action") == "approve"


# ---------------------------------------------------------------------------
# RDD_REVIEW entry node — role access matrix
# ---------------------------------------------------------------------------


class TestRDDReviewEntryRoleAccess:
    """rdd_review_entry_node must allow DD_ENGINEER only; deny all others."""

    @pytest.mark.asyncio
    async def test_dd_engineer_allowed_submit(self) -> None:
        state = _rdd_entry_state("DD_ENGINEER", action="submit_rdd_report")
        result = await rdd_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("rdd_action") == "submit"

    @pytest.mark.asyncio
    async def test_dd_engineer_allowed_final_approve(self) -> None:
        state = _rdd_entry_state("DD_ENGINEER", action="approve_rdd_final")
        result = await rdd_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"].get("rdd_action") == "final_approve"

    @pytest.mark.asyncio
    async def test_mall_manager_denied_from_rdd_entry(self) -> None:
        state = _rdd_entry_state("MALL_MANAGER")
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert "permission" in result["response_message"].lower() or "dd" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_fm_manager_denied_from_rdd_entry(self) -> None:
        state = _rdd_entry_state("FM_MANAGER")
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_operations_denied_from_rdd_entry(self) -> None:
        state = _rdd_entry_state("OPERATIONS")
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_unknown_role_denied_from_rdd_entry(self) -> None:
        state = _rdd_entry_state("SUPER_ADMIN")
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"


# ---------------------------------------------------------------------------
# RDD API submission node — role enforcement for submit (Phase 3a)
# ---------------------------------------------------------------------------


class TestRDDApiSubmitRoleAccess:
    """rdd_api_submission_node must reject non-DD_ENGINEER roles for submit."""

    @pytest.mark.asyncio
    async def test_dd_engineer_can_submit(self) -> None:
        state = _rdd_submit_api_state("DD_ENGINEER")

        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                submit_report=AsyncMock(
                    return_value=ServiceRequestCreationResult(
                        sr_id="sr-role-test-001",
                        endpoint="mock://service-requests",
                        request_payload={},
                        response_payload={"id": "sr-role-test-001", "status": "REPORT_SUBMITTED"},
                        latency_ms=5,
                        status_code=201,
                    )
                )
            ),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["rdd_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_fm_manager_cannot_submit_rdd_report(self) -> None:
        state = _rdd_submit_api_state("FM_MANAGER")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_operations_cannot_submit_rdd_report(self) -> None:
        state = _rdd_submit_api_state("OPERATIONS")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_mall_manager_cannot_submit_rdd_report(self) -> None:
        state = _rdd_submit_api_state("MALL_MANAGER")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()


# ---------------------------------------------------------------------------
# RDD API submission node — role enforcement for final approve (Phase 3b)
# ---------------------------------------------------------------------------


class TestRDDApiFinalApproveRoleAccess:
    """rdd_api_submission_node must reject non-DD_ENGINEER roles for final approve."""

    @pytest.mark.asyncio
    async def test_dd_engineer_can_final_approve(self) -> None:
        state = _rdd_final_approve_api_state("DD_ENGINEER")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(patch_service_request=AsyncMock(return_value=_mock_patch_success())),
        ):
            result = await rdd_api_submission_node(state)
        assert result["workflow_stage"] == "SR_COMPLETED"
        assert result["backend_refs"]["rdd_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_fm_manager_cannot_final_approve(self) -> None:
        state = _rdd_final_approve_api_state("FM_MANAGER")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_operations_cannot_final_approve(self) -> None:
        state = _rdd_final_approve_api_state("OPERATIONS")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_mall_manager_cannot_final_approve(self) -> None:
        state = _rdd_final_approve_api_state("MALL_MANAGER")
        with patch(
            "app.agents.graph.nodes.handover.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()
