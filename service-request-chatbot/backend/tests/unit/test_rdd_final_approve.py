"""Unit tests for the RDD final approval path (Phase 3b).

Coverage
--------
build_rdd_approve_payload:
  - Returns correct shape with APPROVED status
  - service_request_id matches backend_refs["sr_id"]
  - service_category and sub_category correct
  - Falls back to create_payload for tenant/property IDs
  - Optional comment included when provided

rdd_review_entry_node:
  - approve_rdd_final → rdd_action="final_approve"
  - submit_rdd_report still → rdd_action="submit" (existing path unchanged)

rdd_payload_builder_node:
  - rdd_action="final_approve" → builds approve payload (not report payload)
  - rdd_action="submit" → builds report payload (existing path)
  - Both paths write to backend_refs["rdd_payload"]

rdd_api_submission_node:
  - rdd_action="final_approve" → calls patch_service_request (not submit_report)
  - Final approve success → workflow_stage=SR_COMPLETED, rdd_status=APPROVED
  - Final approve API failure → status=FAILED, no workflow_stage change
  - DD_ENGINEER permission check fires for final_approve
  - Non-DD role attempting final_approve → permission denied

sr_status_sync_node:
  - platform_status=REPORT_SUBMITTED → backend_refs["rdd_status"]="REPORT_SUBMITTED"
  - platform_status=APPROVED → backend_refs["rdd_status"]="APPROVED"
  - Other statuses → rdd_status not set

rdd_api_submission_node (Phase 3a correction):
  - submit_report success → rdd_status=REPORT_SUBMITTED, NO workflow_stage=SR_COMPLETED
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph.nodes.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.nodes.rdd_payload_builder_node import rdd_payload_builder_node
from app.agents.graph.nodes.rdd_review_entry_node import rdd_review_entry_node
from app.agents.graph.nodes.sr_status_sync_node import sr_status_sync_node
from app.agents.services.payload_builder_service import (
    build_rdd_approve_payload,
    build_rdd_report_payload,
)
from app.agents.services.service_request_api_service import ServiceRequestCreationResult
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-rdd-final-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {},
        "backend_refs": {},
        "action_override": None,
        "workflow_stage": "RDD_REVIEW",
    }
    base.update(kwargs)
    return base


def _rdd_backend_refs(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sr_id": "sr-rdd-001",
        "create_payload": {
            "payload": {
                "tenant_profile_id": 116,
                "property_id": 10,
                "title": "Test RDD SR",
            },
        },
        "uploaded_documents": ["fm-doc-001"],
        "rdd_document_id": "rdd-doc-001",
    }
    base.update(kwargs)
    return base


def _dd_engineer_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="dd_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["DD_ENGINEER"],
    )


def _fm_manager_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="fm_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["FM_MANAGER"],
    )


def _mock_patch_success(sr_id: str = "sr-rdd-001") -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id=sr_id,
        endpoint=f"mock://service-requests/{sr_id}",
        request_payload={},
        response_payload={"success": True, "id": sr_id},
        latency_ms=10,
        status_code=200,
    )


def _mock_patch_failure() -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id=None,
        endpoint="mock://service-requests/sr-rdd-001",
        request_payload={},
        response_payload=None,
        latency_ms=10,
        status_code=500,
        error="Internal Server Error",
    )


def _mock_submit_success(sr_id: str = "sr-rdd-001") -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id=sr_id,
        endpoint="mock://service-requests",
        request_payload={},
        response_payload={"id": sr_id, "status": "REPORT_SUBMITTED"},
        latency_ms=12,
        status_code=201,
    )


# ---------------------------------------------------------------------------
# build_rdd_approve_payload
# ---------------------------------------------------------------------------


class TestBuildRddApprovePayload:
    def test_top_level_status_is_approved(self) -> None:
        refs = {"sr_id": "sr-001", "tenant_profile_id": 99, "property_id": 5}
        payload = build_rdd_approve_payload(refs)
        assert payload["status"] == "APPROVED"

    def test_inner_payload_current_sr_status_is_report_submitted(self) -> None:
        # current_sr_status is the pre-condition value (state before this action),
        # matching the Postman collection contract for the PATCH final approve call.
        refs = {"sr_id": "sr-001", "tenant_profile_id": 99, "property_id": 5}
        payload = build_rdd_approve_payload(refs)
        assert payload["payload"]["current_sr_status"] == "REPORT_SUBMITTED"

    def test_service_request_id_matches_sr_id(self) -> None:
        refs = {"sr_id": "sr-xyz-001"}
        payload = build_rdd_approve_payload(refs)
        assert payload["service_request_id"] == "sr-xyz-001"

    def test_sr_id_in_inner_payload(self) -> None:
        refs = {"sr_id": "sr-xyz-001"}
        payload = build_rdd_approve_payload(refs)
        assert payload["payload"]["sr_id"] == "sr-xyz-001"

    def test_service_category_correct(self) -> None:
        payload = build_rdd_approve_payload({"sr_id": "sr-001"})
        assert payload["service_category"] == "FIT_OUT_AND_HANDOVER"
        assert payload["sub_category"] == "HANDOVER"

    def test_comment_included_when_provided(self) -> None:
        refs = {"sr_id": "sr-001"}
        payload = build_rdd_approve_payload(refs, comment="All good")
        assert payload["payload"]["comment"] == "All good"

    def test_empty_comment_default(self) -> None:
        refs = {"sr_id": "sr-001"}
        payload = build_rdd_approve_payload(refs)
        assert payload["payload"]["comment"] == ""

    def test_falls_back_to_create_payload_for_tenant_profile_id(self) -> None:
        """tenant_profile_id should come from create_payload when not directly on refs."""
        refs = {
            "sr_id": "sr-001",
            "create_payload": {"payload": {"tenant_profile_id": 42, "property_id": 7}},
        }
        payload = build_rdd_approve_payload(refs)
        assert payload["tenant_profile_id"] == 42
        assert payload["property_id"] == 7

    def test_direct_ids_take_precedence_over_create_payload(self) -> None:
        refs = {
            "sr_id": "sr-001",
            "tenant_profile_id": 99,
            "property_id": 55,
            "create_payload": {"payload": {"tenant_profile_id": 1, "property_id": 2}},
        }
        payload = build_rdd_approve_payload(refs)
        assert payload["tenant_profile_id"] == 99
        assert payload["property_id"] == 55


# ---------------------------------------------------------------------------
# rdd_review_entry_node — approve_rdd_final action
# ---------------------------------------------------------------------------


class TestRDDEntryNodeFinalApprove:
    @pytest.mark.asyncio
    async def test_approve_rdd_final_sets_rdd_action(self) -> None:
        state = _state(action_override="approve_rdd_final", backend_refs={})
        result = await rdd_review_entry_node(state)
        assert result["backend_refs"]["rdd_action"] == "final_approve"

    @pytest.mark.asyncio
    async def test_submit_rdd_report_still_sets_submit(self) -> None:
        """Existing path must remain unchanged."""
        state = _state(action_override="submit_rdd_report", backend_refs={})
        result = await rdd_review_entry_node(state)
        assert result["backend_refs"]["rdd_action"] == "submit"

    @pytest.mark.asyncio
    async def test_approve_rdd_final_returns_backend_refs_only(self) -> None:
        state = _state(action_override="approve_rdd_final", backend_refs={"sr_id": "sr-001"})
        result = await rdd_review_entry_node(state)
        assert "rdd_action" in result["backend_refs"]
        assert "status" not in result


# ---------------------------------------------------------------------------
# rdd_payload_builder_node — branch on rdd_action
# ---------------------------------------------------------------------------


class TestRDDPayloadBuilderBranching:
    @pytest.mark.asyncio
    async def test_final_approve_builds_approve_payload(self) -> None:
        backend_refs = _rdd_backend_refs(rdd_action="final_approve")
        state = _state(backend_refs=backend_refs)
        result = await rdd_payload_builder_node(state)

        payload = result["backend_refs"]["rdd_payload"]
        assert payload["status"] == "APPROVED"
        assert payload["payload"]["current_sr_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_submit_action_builds_report_payload(self) -> None:
        backend_refs = _rdd_backend_refs(rdd_action="submit")
        state = _state(
            collected_data={
                "guideLineLink": "https://example.com/guide",
                "actual_handover_date": "2026-07-01",
                "fitout_start_date": "2026-07-05",
                "fitout_end_date": "2026-08-01",
                "trading_date": "2026-08-15",
            },
            backend_refs=backend_refs,
        )
        result = await rdd_payload_builder_node(state)

        payload = result["backend_refs"]["rdd_payload"]
        assert payload["status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_both_paths_write_rdd_payload_to_backend_refs(self) -> None:
        for action in ("final_approve", "submit"):
            refs = _rdd_backend_refs(rdd_action=action)
            collected = {
                "guideLineLink": "https://example.com",
                "actual_handover_date": "2026-07-01",
                "fitout_start_date": "2026-07-05",
                "fitout_end_date": "2026-08-01",
                "trading_date": "2026-08-15",
            } if action == "submit" else {}
            state = _state(collected_data=collected, backend_refs=refs)
            result = await rdd_payload_builder_node(state)
            assert "rdd_payload" in result["backend_refs"], f"rdd_payload missing for action={action}"

    @pytest.mark.asyncio
    async def test_missing_sr_id_returns_failed(self) -> None:
        state = _state(backend_refs={"rdd_action": "final_approve"})
        result = await rdd_payload_builder_node(state)
        assert result["status"] == "FAILED"


# ---------------------------------------------------------------------------
# rdd_api_submission_node — final_approve branch
# ---------------------------------------------------------------------------


class TestRDDApiSubmissionFinalApprove:
    @pytest.mark.asyncio
    async def test_final_approve_calls_patch_not_submit(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="final_approve",
            rdd_payload={"status": "APPROVED", "payload": {"current_sr_status": "REPORT_SUBMITTED"}},
        )
        state = _state(backend_refs=backend_refs, auth=_dd_engineer_auth())

        mock_svc = AsyncMock()
        mock_svc.patch_service_request = AsyncMock(return_value=_mock_patch_success())
        mock_svc.submit_report = AsyncMock()

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await rdd_api_submission_node(state)

        mock_svc.patch_service_request.assert_called_once()
        mock_svc.submit_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_approve_success_sets_sr_completed(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="final_approve",
            rdd_payload={"status": "APPROVED", "payload": {"current_sr_status": "REPORT_SUBMITTED"}},
        )
        state = _state(backend_refs=backend_refs, auth=_dd_engineer_auth())

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(patch_service_request=AsyncMock(return_value=_mock_patch_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result["workflow_stage"] == "SR_COMPLETED"
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_final_approve_success_sets_rdd_status_approved(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="final_approve",
            rdd_payload={"status": "APPROVED", "payload": {"current_sr_status": "REPORT_SUBMITTED"}},
        )
        state = _state(backend_refs=backend_refs, auth=_dd_engineer_auth())

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(patch_service_request=AsyncMock(return_value=_mock_patch_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result["backend_refs"]["rdd_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_final_approve_api_failure_returns_failed(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="final_approve",
            rdd_payload={"status": "APPROVED", "payload": {"current_sr_status": "REPORT_SUBMITTED"}},
        )
        state = _state(backend_refs=backend_refs, auth=_dd_engineer_auth())

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(patch_service_request=AsyncMock(return_value=_mock_patch_failure())),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "FAILED"
        assert "workflow_stage" not in result

    @pytest.mark.asyncio
    async def test_final_approve_non_dd_role_denied(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="final_approve",
            rdd_payload={"status": "APPROVED", "payload": {"current_sr_status": "REPORT_SUBMITTED"}},
        )
        state = _state(backend_refs=backend_refs, auth=_fm_manager_auth())

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()


# ---------------------------------------------------------------------------
# rdd_api_submission_node — Phase 3a behavior correction
# ---------------------------------------------------------------------------


class TestRDDApiSubmissionPhase3a:
    @pytest.mark.asyncio
    async def test_submit_success_sets_rdd_status_report_submitted(self) -> None:
        backend_refs = _rdd_backend_refs(
            rdd_action="submit",
            rdd_payload={"status": "REPORT_SUBMITTED"},
        )
        state = _state(backend_refs=backend_refs)

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(submit_report=AsyncMock(return_value=_mock_submit_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["rdd_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_submit_success_does_not_set_sr_completed(self) -> None:
        """Phase 3a (submit) must NOT advance to SR_COMPLETED — only final_approve does."""
        backend_refs = _rdd_backend_refs(
            rdd_action="submit",
            rdd_payload={"status": "REPORT_SUBMITTED"},
        )
        state = _state(backend_refs=backend_refs)

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(submit_report=AsyncMock(return_value=_mock_submit_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result.get("workflow_stage") != "SR_COMPLETED"


# ---------------------------------------------------------------------------
# sr_status_sync_node — rdd_status storage
# ---------------------------------------------------------------------------


class TestSRStatusSyncRddStatus:
    @pytest.mark.asyncio
    async def test_report_submitted_status_stored(self) -> None:
        state = {
            "session_id": "sess-sync-001",
            "user_id": "user-001",
            "trace_manager": None,
            "trace_id": None,
            "workflow_stage": "RDD_REVIEW",
            "backend_refs": {"sr_id": "sr-sync-001"},
        }

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-sync-001",
            endpoint="mock://service-requests/sr-sync-001",
            request_payload={},
            response_payload={
                "_sr_status": "REPORT_SUBMITTED",
                "_service_request_operations": [
                    {"role": "DD_ENGINEER", "status": "IN_PROGRESS"}
                ],
            },
            latency_ms=5,
            status_code=200,
        )
        with patch(
            "app.agents.graph.nodes.sr_status_sync_node.get_service_request_api_service",
            return_value=AsyncMock(get_service_request=AsyncMock(return_value=mock_result)),
        ):
            result = await sr_status_sync_node(state)

        assert result["backend_refs"]["rdd_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_approved_status_stored(self) -> None:
        state = {
            "session_id": "sess-sync-002",
            "user_id": "user-001",
            "trace_manager": None,
            "trace_id": None,
            "workflow_stage": "RDD_REVIEW",
            "backend_refs": {"sr_id": "sr-sync-002"},
        }

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-sync-002",
            endpoint="mock://service-requests/sr-sync-002",
            request_payload={},
            response_payload={
                "_sr_status": "APPROVED",
                "_service_request_operations": [],
            },
            latency_ms=5,
            status_code=200,
        )
        with patch(
            "app.agents.graph.nodes.sr_status_sync_node.get_service_request_api_service",
            return_value=AsyncMock(get_service_request=AsyncMock(return_value=mock_result)),
        ):
            result = await sr_status_sync_node(state)

        assert result["backend_refs"]["rdd_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_other_status_does_not_set_rdd_status(self) -> None:
        state = {
            "session_id": "sess-sync-003",
            "user_id": "user-001",
            "trace_manager": None,
            "trace_id": None,
            "workflow_stage": "FM_REVIEW",
            "backend_refs": {"sr_id": "sr-sync-003"},
        }

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-sync-003",
            endpoint="mock://service-requests/sr-sync-003",
            request_payload={},
            response_payload={
                "_sr_status": "IN_PROCESS",
                "_service_request_operations": [{"role": "FM_MANAGER", "status": "IN_PROGRESS"}],
            },
            latency_ms=5,
            status_code=200,
        )
        with patch(
            "app.agents.graph.nodes.sr_status_sync_node.get_service_request_api_service",
            return_value=AsyncMock(get_service_request=AsyncMock(return_value=mock_result)),
        ):
            result = await sr_status_sync_node(state)

        assert "rdd_status" not in result.get("backend_refs", {})
