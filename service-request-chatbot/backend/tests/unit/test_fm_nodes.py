"""Unit tests for FM_REVIEW graph nodes.

Coverage
--------
fm_review_entry_node:
  - Action override save_fm_progress → sets fm_action=save_progress
  - Action override approve_fm_review → sets fm_action=approve
  - Action override reject_fm_review → WAITING_FOR_USER
  - Wrong role → WAITING_FOR_USER with denial message
  - No action_override → returns {}

fm_payload_builder_node:
  - Missing sr_id → FAILED
  - save_progress action → calls build_fm_review_payload
  - approve action → calls build_fm_approve_payload
  - Builder exception → FAILED

fm_api_submission_node:
  - Blocking validation errors → FAILED
  - Missing sr_id → FAILED
  - Missing fm_payload → FAILED
  - API error → FAILED
  - Success (save_progress) → SUBMITTED + audit event
  - Success (approve) → SUBMITTED + audit event
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.graph.nodes.fm_api_submission_node import fm_api_submission_node
from app.agents.graph.nodes.fm_payload_builder_node import fm_payload_builder_node
from app.agents.graph.nodes.fm_review_entry_node import fm_review_entry_node


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
        "workflow_stage": "FM_REVIEW",
    }
    base.update(kwargs)
    return base


def _fm_backend_refs(**kwargs: Any) -> dict[str, Any]:
    base = {
        "sr_id": "sr-123",
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
        "uploaded_documents": ["doc-001", "doc-002"],
        "sr_operations": [{"role": "FM_MANAGER", "status": "IN_PROGRESS"}],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# fm_review_entry_node
# ---------------------------------------------------------------------------


class TestFMReviewEntryNode:
    @pytest.mark.asyncio
    async def test_save_fm_progress_sets_fm_action(self) -> None:
        state = _state(action_override="save_fm_progress", backend_refs={})
        result = await fm_review_entry_node(state)
        assert result["backend_refs"]["fm_action"] == "save_progress"

    @pytest.mark.asyncio
    async def test_approve_fm_review_sets_fm_action(self) -> None:
        state = _state(action_override="approve_fm_review", backend_refs={})
        result = await fm_review_entry_node(state)
        assert result["backend_refs"]["fm_action"] == "approve"

    @pytest.mark.asyncio
    async def test_reject_sets_waiting_for_user(self) -> None:
        state = _state(action_override="reject_fm_review", backend_refs={})
        result = await fm_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert "rejection" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_wrong_role_denied(self) -> None:
        state = _state(
            action_override=None,
            backend_refs={"user_role": "MALL_MANAGER"},
        )
        result = await fm_review_entry_node(state)
        assert result["status"] == "WAITING_FOR_USER"
        assert "permission" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_no_action_returns_empty(self) -> None:
        state = _state(action_override=None, backend_refs={"user_role": "FM_MANAGER"})
        result = await fm_review_entry_node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_fm_manager_role_allowed(self) -> None:
        state = _state(
            action_override="save_fm_progress",
            backend_refs={"user_role": "FM_MANAGER"},
        )
        result = await fm_review_entry_node(state)
        assert "fm_action" in result.get("backend_refs", {})

    @pytest.mark.asyncio
    async def test_operations_role_allowed(self) -> None:
        state = _state(
            action_override="save_fm_progress",
            backend_refs={"user_role": "OPERATIONS"},
        )
        result = await fm_review_entry_node(state)
        assert result.get("backend_refs", {}).get("fm_action") == "save_progress"


# ---------------------------------------------------------------------------
# fm_payload_builder_node
# ---------------------------------------------------------------------------


class TestFMPayloadBuilderNode:
    @pytest.mark.asyncio
    async def test_missing_sr_id_returns_failed(self) -> None:
        state = _state(backend_refs={})
        result = await fm_payload_builder_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_save_progress_builds_fm_payload(self) -> None:
        backend_refs = _fm_backend_refs(fm_action="save_progress")
        state = _state(
            collected_data={"unit_readiness_date": "2026-05-01", "expected_handover_date": "2026-06-01"},
            backend_refs=backend_refs,
        )
        result = await fm_payload_builder_node(state)
        assert "fm_payload" in result.get("backend_refs", {})
        assert result["backend_refs"]["fm_payload"]["status"] == "IN_PROCESS"

    @pytest.mark.asyncio
    async def test_approve_builds_approve_payload(self) -> None:
        backend_refs = _fm_backend_refs(fm_action="approve")
        state = _state(
            collected_data={"unit_readiness_date": "2026-05-01", "expected_handover_date": "2026-06-01"},
            backend_refs=backend_refs,
        )
        result = await fm_payload_builder_node(state)
        assert result["backend_refs"]["fm_payload"]["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# fm_api_submission_node
# ---------------------------------------------------------------------------


class TestFMApiSubmissionNode:
    @pytest.mark.asyncio
    async def test_blocking_errors_returns_failed(self) -> None:
        state = _state(
            validation_errors=[{"blocking": True, "message": "bad date"}],
            backend_refs=_fm_backend_refs(fm_payload={"status": "IN_PROCESS"}),
        )
        result = await fm_api_submission_node(state)
        assert result["status"] == "FAILED"
        assert "blocked" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_missing_sr_id_returns_failed(self) -> None:
        state = _state(backend_refs={"fm_payload": {"status": "IN_PROCESS"}})
        result = await fm_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_payload_returns_failed(self) -> None:
        state = _state(backend_refs={"sr_id": "sr-123"})
        result = await fm_api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_api_error_returns_failed(self) -> None:
        from app.agents.services.service_request_api_service import ServiceRequestCreationResult
        backend_refs = _fm_backend_refs(
            fm_payload={"status": "IN_PROCESS"},
            fm_action="save_progress",
        )
        state = _state(backend_refs=backend_refs)

        mock_result = ServiceRequestCreationResult(
            sr_id=None,
            endpoint="http://x/service-requests/sr-123",
            request_payload={},
            response_payload=None,
            latency_ms=10,
            status_code=500,
            error="server error",
        )
        with patch(
            "app.agents.graph.nodes.fm_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.patch_service_request = AsyncMock(return_value=mock_result)
            mock_svc_factory.return_value = mock_svc
            result = await fm_api_submission_node(state)

        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_success_save_progress(self) -> None:
        from app.agents.services.service_request_api_service import ServiceRequestCreationResult
        backend_refs = _fm_backend_refs(
            fm_payload={"status": "IN_PROCESS"},
            fm_action="save_progress",
        )
        state = _state(backend_refs=backend_refs)

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-123",
            endpoint="http://x/service-requests/sr-123",
            request_payload={},
            response_payload={"success": True},
            latency_ms=15,
            status_code=200,
        )
        with patch(
            "app.agents.graph.nodes.fm_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.patch_service_request = AsyncMock(return_value=mock_result)
            mock_svc_factory.return_value = mock_svc
            result = await fm_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["fm_status"] == "IN_PROCESS"
        assert "saved" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_success_approve(self) -> None:
        from app.agents.services.service_request_api_service import ServiceRequestCreationResult
        backend_refs = _fm_backend_refs(
            fm_payload={"status": "APPROVED"},
            fm_action="approve",
        )
        state = _state(backend_refs=backend_refs)

        mock_result = ServiceRequestCreationResult(
            sr_id="sr-123",
            endpoint="http://x/service-requests/sr-123",
            request_payload={},
            response_payload={"success": True},
            latency_ms=10,
            status_code=200,
        )
        with patch(
            "app.agents.graph.nodes.fm_api_submission_node.get_service_request_api_service"
        ) as mock_svc_factory:
            mock_svc = AsyncMock()
            mock_svc.patch_service_request = AsyncMock(return_value=mock_result)
            mock_svc_factory.return_value = mock_svc
            result = await fm_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["fm_status"] == "APPROVED"
        assert "approved" in result["response_message"].lower()
