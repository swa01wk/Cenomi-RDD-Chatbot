"""Integration tests for the RDD_REVIEW end-to-end flow.

Covers both Phase 3a (submit report) and Phase 3b (final approve):

Phase 3a — report submission:
  document_upload_node → rdd_payload_builder_node → rdd_api_submission_node (submit)
  Expected outcomes: rdd_status=REPORT_SUBMITTED; workflow_stage stays RDD_REVIEW

Phase 3b — final approval:
  rdd_review_entry_node (approve_rdd_final) → rdd_payload_builder_node → rdd_api_submission_node (final_approve)
  Expected outcomes: rdd_status=APPROVED; workflow_stage=SR_COMPLETED

Also covers:
- Dates converted to DD/MM/YYYY in the submitted payload
- Wrong role (FM_MANAGER) attempting RDD final approve → permission denied
- Chained test: Phase 3a result state → directly into Phase 3b → SR_COMPLETED
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph.nodes.document_upload_node import document_upload_node
from app.agents.graph.nodes.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.nodes.rdd_payload_builder_node import rdd_payload_builder_node
from app.agents.graph.nodes.rdd_review_entry_node import rdd_review_entry_node
from app.agents.services.service_request_api_service import ServiceRequestCreationResult
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dd_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="dd_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["DD_ENGINEER"],
    )


def _fm_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="fm_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["FM_MANAGER"],
    )


_RDD_COLLECTED: dict[str, Any] = {
    "guideLineLink": "https://cenomi.example.com/guidelines",
    "actual_handover_date": "2026-07-01",
    "fitout_start_date": "2026-07-05",
    "fitout_end_date": "2026-08-01",
    "trading_date": "2026-08-15",
}


def _base_rdd_state(rdd_action: str = "submit", **kwargs: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "session_id": "rdd-integ-sess-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": dict(_RDD_COLLECTED),
        "backend_refs": {
            "sr_id": "sr-rdd-integ-001",
            "user_role": "DD_ENGINEER",
            "rdd_action": rdd_action,
            "create_payload": {
                "payload": {
                    "mall": "Dubai Mall",
                    "brand": "BrandX",
                    "lease": "LC-001",
                    "title": "RDD Integration Test SR",
                    "tenant_profile_id": 116,
                    "property_id": 10,
                    "unit_readiness_date": "2026-06-18",
                    "expected_handover_date": "2026-06-25",
                },
                "lease_id": 456,
            },
            "uploaded_documents": ["fm-doc-001"],
        },
        "documents": [
            {"document_id": "rdd-report-001", "document_type_id": "DR_SR_HANDOVER_REPORT"},
        ],
        "workflow_stage": "RDD_REVIEW",
        "action_override": None,
        "auth": _dd_auth(),
    }
    state.update(kwargs)
    return state


def _mock_submit_success(sr_id: str = "sr-rdd-integ-001") -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id=sr_id,
        endpoint="mock://service-requests",
        request_payload={},
        response_payload={"id": sr_id, "status": "REPORT_SUBMITTED"},
        latency_ms=12,
        status_code=201,
    )


def _mock_patch_success(sr_id: str = "sr-rdd-integ-001") -> ServiceRequestCreationResult:
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
        endpoint="mock://service-requests/sr-rdd-integ-001",
        request_payload={},
        response_payload=None,
        latency_ms=10,
        status_code=500,
        error="Internal Server Error",
    )


# ---------------------------------------------------------------------------
# Phase 3a — Document upload bridge in RDD context
# ---------------------------------------------------------------------------


class TestRDDDocumentBridge:
    @pytest.mark.asyncio
    async def test_rdd_report_doc_partitioned_correctly(self) -> None:
        state = _base_rdd_state()
        result = await document_upload_node(state)

        assert result["backend_refs"]["rdd_document_id"] == "rdd-report-001"

    @pytest.mark.asyncio
    async def test_fm_docs_preserved_during_rdd_upload(self) -> None:
        state = _base_rdd_state()
        result = await document_upload_node(state)

        # Pre-existing FM docs must still be there
        assert "fm-doc-001" in result["backend_refs"]["uploaded_documents"]


# ---------------------------------------------------------------------------
# Phase 3a — Report submission
# ---------------------------------------------------------------------------


class TestRDDPhase3aSubmit:
    @pytest.mark.asyncio
    async def test_report_payload_has_report_submitted_status(self) -> None:
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_document_id"] = "rdd-report-001"

        result = await rdd_payload_builder_node(state)
        assert result["backend_refs"]["rdd_payload"]["status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_payload_dates_in_ddmmyyyy_format(self) -> None:
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_document_id"] = "rdd-report-001"

        result = await rdd_payload_builder_node(state)
        doc_status_map = result["backend_refs"]["rdd_payload"]["payload"]["document_status_map"]
        rdd_entry = next(
            (e for e in doc_status_map if e.get("document_status") == "APPROVED"),
            None,
        )
        assert rdd_entry is not None
        assert rdd_entry["actual_handover_date"] == "01/07/2026"
        assert rdd_entry["fitout_start_date"] == "05/07/2026"
        assert rdd_entry["fitout_end_date"] == "01/08/2026"
        assert rdd_entry["trading_date"] == "15/08/2026"

    @pytest.mark.asyncio
    async def test_payload_includes_rdd_document_id(self) -> None:
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_document_id"] = "rdd-report-001"

        result = await rdd_payload_builder_node(state)
        doc_ids = result["backend_refs"]["rdd_payload"]["payload"]["documents_ids"]
        assert "rdd-report-001" in doc_ids

    @pytest.mark.asyncio
    async def test_submit_success_sets_rdd_status_report_submitted(self) -> None:
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_payload"] = {"status": "REPORT_SUBMITTED"}
        state["backend_refs"]["rdd_document_id"] = "rdd-report-001"

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(submit_report=AsyncMock(return_value=_mock_submit_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["rdd_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_submit_success_does_not_advance_to_sr_completed(self) -> None:
        """Phase 3a: report submitted; SR stays in RDD_REVIEW for final approval."""
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_payload"] = {"status": "REPORT_SUBMITTED"}

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(submit_report=AsyncMock(return_value=_mock_submit_success())),
        ):
            result = await rdd_api_submission_node(state)

        assert result.get("workflow_stage") != "SR_COMPLETED"

    @pytest.mark.asyncio
    async def test_submit_calls_submit_report_not_patch(self) -> None:
        state = _base_rdd_state(rdd_action="submit")
        state["backend_refs"]["rdd_payload"] = {"status": "REPORT_SUBMITTED"}

        mock_svc = AsyncMock()
        mock_svc.submit_report = AsyncMock(return_value=_mock_submit_success())
        mock_svc.patch_service_request = AsyncMock()

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await rdd_api_submission_node(state)

        mock_svc.submit_report.assert_called_once()
        mock_svc.patch_service_request.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 3b — Final approval
# ---------------------------------------------------------------------------


class TestRDDPhase3bFinalApprove:
    @pytest.mark.asyncio
    async def test_final_approve_action_sets_rdd_action(self) -> None:
        state = _base_rdd_state()
        state["action_override"] = "approve_rdd_final"
        result = await rdd_review_entry_node(state)
        assert result["backend_refs"]["rdd_action"] == "final_approve"

    @pytest.mark.asyncio
    async def test_approve_payload_has_approved_status(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")

        result = await rdd_payload_builder_node(state)
        assert result["backend_refs"]["rdd_payload"]["status"] == "APPROVED"
        # current_sr_status is the pre-action state (Postman contract)
        assert result["backend_refs"]["rdd_payload"]["payload"]["current_sr_status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_final_approve_success_sets_sr_completed(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")
        state["backend_refs"]["rdd_payload"] = {
            "status": "APPROVED",
            "payload": {"current_sr_status": "REPORT_SUBMITTED", "sr_id": "sr-rdd-integ-001"},
        }

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_success())
            ),
        ):
            result = await rdd_api_submission_node(state)

        assert result["workflow_stage"] == "SR_COMPLETED"
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_final_approve_success_sets_rdd_status_approved(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")
        state["backend_refs"]["rdd_payload"] = {
            "status": "APPROVED",
            "payload": {"current_sr_status": "REPORT_SUBMITTED"},
        }

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_success())
            ),
        ):
            result = await rdd_api_submission_node(state)

        assert result["backend_refs"]["rdd_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_final_approve_calls_patch_not_submit_report(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")
        state["backend_refs"]["rdd_payload"] = {
            "status": "APPROVED",
            "payload": {"current_sr_status": "REPORT_SUBMITTED"},
        }

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
    async def test_final_approve_api_failure_returns_failed_no_stage_change(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")
        state["backend_refs"]["rdd_payload"] = {
            "status": "APPROVED",
            "payload": {"current_sr_status": "REPORT_SUBMITTED"},
        }

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_failure())
            ),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "FAILED"
        assert "workflow_stage" not in result

    @pytest.mark.asyncio
    async def test_wrong_role_cannot_final_approve(self) -> None:
        state = _base_rdd_state(rdd_action="final_approve")
        state["auth"] = _fm_auth()
        state["backend_refs"]["rdd_payload"] = {
            "status": "APPROVED",
            "payload": {"current_sr_status": "REPORT_SUBMITTED"},
        }

        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await rdd_api_submission_node(state)

        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()


# ---------------------------------------------------------------------------
# Chained Phase 3a → Phase 3b
# ---------------------------------------------------------------------------


class TestRDDChainedPhase3aTo3b:
    @pytest.mark.asyncio
    async def test_submit_result_feeds_into_final_approve(self) -> None:
        """Full lifecycle: upload doc → submit → take result → final approve → SR_COMPLETED."""

        # ── Phase 3a: Upload + submit report ──────────────────────────────────
        state_3a = _base_rdd_state(rdd_action="submit")

        # Doc upload
        doc_result = await document_upload_node(state_3a)
        state_3a["backend_refs"].update(doc_result["backend_refs"])
        assert state_3a["backend_refs"]["rdd_document_id"] == "rdd-report-001"

        # Build report payload
        pb_result = await rdd_payload_builder_node(state_3a)
        state_3a["backend_refs"].update(pb_result["backend_refs"])

        # Submit
        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(submit_report=AsyncMock(return_value=_mock_submit_success())),
        ):
            submit_result = await rdd_api_submission_node(state_3a)

        assert submit_result["status"] == "SUBMITTED"
        assert submit_result["backend_refs"]["rdd_status"] == "REPORT_SUBMITTED"

        # ── Phase 3b: Final approve (using Phase 3a result state) ─────────────
        # Merge Phase 3a result into a new state; override rdd_action to final_approve
        state_3b = _base_rdd_state(rdd_action="final_approve")
        state_3b["backend_refs"].update(submit_result["backend_refs"])
        # Ensure rdd_action is final_approve (Phase 3a result contained "submit")
        state_3b["backend_refs"]["rdd_action"] = "final_approve"

        # Build approve payload
        approve_pb = await rdd_payload_builder_node(state_3b)
        state_3b["backend_refs"].update(approve_pb["backend_refs"])

        assert state_3b["backend_refs"]["rdd_payload"]["status"] == "APPROVED"
        assert state_3b["backend_refs"]["rdd_payload"]["payload"]["current_sr_status"] == "REPORT_SUBMITTED"

        # Final approve
        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_success())
            ),
        ):
            final_result = await rdd_api_submission_node(state_3b)

        assert final_result["workflow_stage"] == "SR_COMPLETED"
        assert final_result["backend_refs"]["rdd_status"] == "APPROVED"
        assert final_result["status"] == "SUBMITTED"
