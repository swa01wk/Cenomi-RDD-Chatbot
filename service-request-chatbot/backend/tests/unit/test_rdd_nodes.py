"""Unit tests for RDD_REVIEW graph nodes.

Coverage
--------
rdd_review_entry_node:
  - Action override submit_rdd_report → sets rdd_action=submit
  - Wrong role → WAITING_FOR_USER with denial message
  - No action_override → returns {}

rdd_payload_builder_node:
  - Missing sr_id → FAILED
  - Success with all date fields → payload has status=REPORT_SUBMITTED
  - Date conversion: ISO 2026-05-12 → DD/MM/YYYY 12/05/2026

rdd_api_submission_node:
  - Blocking errors → FAILED
  - Missing sr_id → FAILED
  - Missing payload → FAILED
  - API error → FAILED
  - Success → SUBMITTED + workflow_stage=SR_COMPLETED
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph.nodes.rdd_api_submission_node import rdd_api_submission_node
from app.agents.graph.nodes.rdd_payload_builder_node import rdd_payload_builder_node
from app.agents.graph.nodes.rdd_review_entry_node import rdd_review_entry_node
from app.agents.services.payload_builder_service import _to_ddmmyyyy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-001",
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
    base = {
        "sr_id": "sr-456",
        "create_payload": {
            "payload": {
                "mall": "Dubai Mall",
                "brand": "BrandX",
                "lease": "LC-001",
                "title": "Test SR",
                "tenant_profile_id": 116,
                "property_id": 10,
            },
            "lease_id": 456,
        },
        "uploaded_documents": ["doc-fm-001"],
        "rdd_document_id": "doc-rdd-001",
    }
    base.update(kwargs)
    return base


_RDD_COLLECTED = {
    "guideLineLink": "https://cenomi.com/guidelines",
    "actual_handover_date": "2026-05-12",
    "fitout_start_date": "2026-05-14",
    "fitout_end_date": "2026-05-20",
    "trading_date": "2026-05-25",
}


# ---------------------------------------------------------------------------
# rdd_review_entry_node
# ---------------------------------------------------------------------------


class TestRDDReviewEntryNode:
    @pytest.mark.asyncio
    async def test_submit_rdd_sets_rdd_action(self) -> None:
        state = _state(action_override="submit_rdd_report", backend_refs={})
        result = await rdd_review_entry_node(state)
        assert result["backend_refs"]["rdd_action"] == "submit"

    @pytest.mark.asyncio
    async def test_wrong_role_denied(self) -> None:
        state = _state(
            action_override=None,
            backend_refs={"user_role": "MALL_MANAGER"},
        )
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_no_action_returns_empty(self) -> None:
        state = _state(action_override=None, backend_refs={"user_role": "DD_ENGINEER"})
        result = await rdd_review_entry_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_dd_engineer_role_allowed(self) -> None:
        state = _state(
            action_override="submit_rdd_report",
            backend_refs={"user_role": "DD_ENGINEER"},
        )
        result = await rdd_review_entry_node(state)
        assert result.get("backend_refs", {}).get("rdd_action") == "submit"

    @pytest.mark.asyncio
    async def test_cancel_update_sets_waiting(self) -> None:
        state = _state(action_override="cancel_update", backend_refs={})
        result = await rdd_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"


# ---------------------------------------------------------------------------
# rdd_payload_builder_node
# ---------------------------------------------------------------------------


class TestRDDPayloadBuilderNode:
    @pytest.mark.asyncio
    async def test_missing_sr_id_returns_failed(self) -> None:
        state = _state(backend_refs={})
        result = await rdd_payload_builder_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_success_builds_report_payload(self) -> None:
        state = _state(
            collected_data=_RDD_COLLECTED,
            backend_refs=_rdd_backend_refs(),
        )
        result = await rdd_payload_builder_node(state)
        assert "rdd_payload" in result.get("backend_refs", {})
        payload = result["backend_refs"]["rdd_payload"]
        assert payload["status"] == "REPORT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_rdd_doc_in_documents_ids(self) -> None:
        state = _state(
            collected_data=_RDD_COLLECTED,
            backend_refs=_rdd_backend_refs(),
        )
        result = await rdd_payload_builder_node(state)
        doc_ids = result["backend_refs"]["rdd_payload"]["payload"]["documents_ids"]
        assert "doc-rdd-001" in doc_ids

    @pytest.mark.asyncio
    async def test_date_in_ddmmyyyy_format(self) -> None:
        state = _state(
            collected_data=_RDD_COLLECTED,
            backend_refs=_rdd_backend_refs(),
        )
        result = await rdd_payload_builder_node(state)
        doc_status_map = result["backend_refs"]["rdd_payload"]["payload"]["document_status_map"]
        rdd_entry = next(e for e in doc_status_map if e.get("document_status") == "APPROVED")
        assert rdd_entry["actual_handover_date"] == "12/05/2026"
        assert rdd_entry["fitout_start_date"] == "14/05/2026"


# ---------------------------------------------------------------------------
# Date conversion helper
# ---------------------------------------------------------------------------


class TestToDdMmYyyy:
    def test_iso_to_ddmmyyyy(self) -> None:
        assert _to_ddmmyyyy("2026-05-12") == "12/05/2026"

    def test_already_ddmmyyyy(self) -> None:
        assert _to_ddmmyyyy("12/05/2026") == "12/05/2026"

    def test_passthrough_on_garbage(self) -> None:
        assert _to_ddmmyyyy("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# rdd_api_submission_node
# ---------------------------------------------------------------------------


class TestRDDApiSubmissionNode:
    @pytest.mark.asyncio
    async def test_blocking_errors_returns_failed(self) -> None:
        state = _state(
            validation_errors=[{"blocking": True, "message": "date order invalid"}],
            backend_refs=_rdd_backend_refs(rdd_payload={"status": "REPORT_SUBMITTED"}),
        )
        result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_sr_id_returns_failed(self) -> None:
        state = _state(backend_refs={"rdd_payload": {"status": "REPORT_SUBMITTED"}})
        result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_payload_returns_failed(self) -> None:
        state = _state(backend_refs={"sr_id": "sr-456"})
        result = await rdd_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_api_error_returns_failed(self) -> None:
        from app.agents.services.service_request_api_service import ServiceRequestCreationResult
        backend_refs = _rdd_backend_refs(rdd_payload={"status": "REPORT_SUBMITTED"})
        state = _state(backend_refs=backend_refs)

        mock_result = ServiceRequestCreationResult(
            sr_id=None,
            endpoint="http://x/service-requests",
            request_payload={},
            response_payload=None,
            latency_ms=10,
            status_code=500,
            error="server error",
        )
        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.submit_report = AsyncMock(return_value=mock_result)
            mock_svc_factory.return_value = mock_svc
            result = await rdd_api_submission_node(state)

        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_success_sets_completed(self) -> None:
        from app.agents.services.service_request_api_service import ServiceRequestCreationResult
        backend_refs = _rdd_backend_refs(rdd_payload={"status": "REPORT_SUBMITTED"})
        state = _state(backend_refs=backend_refs)

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-456",
            endpoint="http://x/service-requests",
            request_payload={},
            response_payload={"id": "sr-456", "status": "REPORT_SUBMITTED"},
            latency_ms=12,
            status_code=201,
        )
        with patch(
            "app.agents.graph.nodes.rdd_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.submit_report = AsyncMock(return_value=mock_result)
            mock_svc_factory.return_value = mock_svc
            result = await rdd_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["workflow_stage"] == "SR_COMPLETED"
        assert "sr-456" in result["response_message"]
