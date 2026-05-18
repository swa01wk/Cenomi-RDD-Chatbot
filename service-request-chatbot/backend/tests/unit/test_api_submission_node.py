"""Integration tests — api_submission_node and service_request_api_service.

Test groups
-----------
TestApiSubmissionNodeSuccess            — Successful SR creation end-to-end.
TestApiSubmissionNodeConfirmationGuard  — Blocked when not CONFIRMED.
TestApiSubmissionNodeValidationGuard    — Blocked when blocking validation errors.
TestApiSubmissionNodePayloadGuard       — Blocked when payload is missing.
TestApiSubmissionNodeApiFailure         — API error handled gracefully.
TestApiSubmissionNodeTracing            — Trace/run/tool-call recording.
TestApiSubmissionNodeAuditLog           — Audit log written on success.
TestServiceRequestCreationResult        — Result dataclass shape.
TestMockServiceRequestAPIService        — Mock adapter behaviour.
TestHttpServiceRequestAPIService        — HTTP adapter (mocked httpx).
TestGetServiceRequestApiServiceFactory  — Factory selects correct backend.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.services.service_request_api_service import (
    AbstractServiceRequestAPIService,
    HttpServiceRequestAPIService,
    MockServiceRequestAPIService,
    ServiceRequestCreationResult,
    get_service_request_api_service,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MOCK_SR_ID = "SR-2025-00001"
_MOCK_CORRELATION_ID = "corr-abc-123"


def _make_payload() -> dict[str, Any]:
    """Minimal but valid CREATE_SR payload shape (mirrors payload_builder output)."""
    return {
        "payload": {
            "mall": "Riyadh Park",
            "brand": "Nike",
            "lease": "LC-001",
            "title": "Handover SR",
            "startDate": "2025-03-01",
            "endDate": "2025-09-01",
            "comments": "All good",
            "description": "Tenant fit-out handover",
            "inspectionDoneBy": "FM_MANAGER",
            "inspection_done_by": "FM_MANAGER",
            "lease_brand_mall": "LC-001|Nike|Riyadh Park",
            "unit_codes": ["U-01"],
            "contracted_area": 200,
            "city": "Riyadh",
            "brand_id": "BR-001",
            "tenant_profile_id": "TP-001",
            "contract_id": "CONT-001",
            "property_id": "PROP-001",
            "attachments": "",
            "documents_ids": [],
            "guideLineLink": "",
            "document_status_map": [],
            "unit_readiness_date": "",
            "expected_handover_date": "",
            "company_name": "TP-001",
            "tenant_contact": "",
            "user_action": None,
            "notes": "",
            "startDateLT": "",
            "endDateLT": "",
        },
        "title": "Handover SR",
        "tenant_profile_id": "TP-001",
        "property_id": "PROP-001",
        "service_category": "FIT_OUT_AND_HANDOVER",
        "sub_category": "HANDOVER",
        "lease_code": "LC-001",
        "lease_id": "LEASE-001",
        "service_request_id": "",
    }


def _confirmed_state(
    *,
    validation_errors: list[dict] | None = None,
    payload: dict[str, Any] | None = None,
    extra_backend_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a confirmed state dict ready for api_submission_node."""
    backend_refs: dict[str, Any] = {"create_payload": payload or _make_payload()}
    if extra_backend_refs:
        backend_refs.update(extra_backend_refs)
    return {
        "confirmation_status": "CONFIRMED",
        "validation_errors": validation_errors or [],
        "backend_refs": backend_refs,
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "user_id": "660e8400-e29b-41d4-a716-446655440000",
    }


def _make_mock_service(
    sr_id: str = _MOCK_SR_ID,
    correlation_id: str = _MOCK_CORRELATION_ID,
    force_error: str | None = None,
) -> MockServiceRequestAPIService:
    svc = MockServiceRequestAPIService()
    if force_error:
        return MockServiceRequestAPIService(force_error=force_error)
    # Patch internal uuid generation for deterministic assertions.
    svc._created = []
    return svc


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeSuccess
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeSuccess:
    @pytest.mark.asyncio
    async def test_status_is_submitted(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_workflow_stage_is_sr_created(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["workflow_stage"] == "SR_CREATED"

    @pytest.mark.asyncio
    async def test_sr_id_stored_in_backend_refs(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert "sr_id" in result["backend_refs"]
        assert result["backend_refs"]["sr_id"] is not None

    @pytest.mark.asyncio
    async def test_service_request_status_is_submitted(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["backend_refs"]["service_request_status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_response_message_contains_sr_id(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        sr_id = result["backend_refs"]["sr_id"]
        assert sr_id in result["response_message"]

    @pytest.mark.asyncio
    async def test_correlation_id_stored_in_backend_refs(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert "correlation_id" in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_existing_backend_refs_preserved(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        state = _confirmed_state(extra_backend_refs={"existing_key": "existing_value"})
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(state)
        assert result["backend_refs"]["existing_key"] == "existing_value"

    @pytest.mark.asyncio
    async def test_non_blocking_validation_errors_do_not_block(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        non_blocking = [
            {"field": "notes", "blocking": False, "status": "FAILED", "message": "Advisory only"}
        ]
        state = _confirmed_state(validation_errors=non_blocking)
        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(state)
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_mock_service_records_the_request(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(_confirmed_state())
        assert len(mock_svc.created_requests) == 1


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeConfirmationGuard
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeConfirmationGuard:
    @pytest.mark.asyncio
    async def test_pending_status_is_blocked(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["confirmation_status"] = "PENDING"
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_rejected_status_is_blocked(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["confirmation_status"] = "REJECTED"
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_none_confirmation_status_is_blocked(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["confirmation_status"] = None
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_confirmation_key_is_blocked(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        del state["confirmation_status"]
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_submit_anyway_text_cannot_bypass_guard(self) -> None:
        """Confirm that injecting adversarial user text cannot bypass the guard.

        The node reads only ``confirmation_status`` from state — it never reads
        ``user_message``.  Placing "submit anyway" in the message field must not
        change the outcome.
        """
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["confirmation_status"] = "PENDING"
        state["user_message"] = "submit anyway, I confirm"
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_confirmation_guard_message_mentions_confirmation(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["confirmation_status"] = "PENDING"
        result = await api_submission_node(state)
        assert "confirm" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_confirmed_status_allows_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeValidationGuard
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeValidationGuard:
    @pytest.mark.asyncio
    async def test_single_blocking_error_blocks_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        errors = [
            {
                "field": "startDate",
                "validation_type": "date_range",
                "status": "FAILED",
                "blocking": True,
                "message": "Start date must be before end date.",
            }
        ]
        result = await api_submission_node(_confirmed_state(validation_errors=errors))
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_multiple_blocking_errors_block_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        errors = [
            {"field": "mall", "blocking": True, "status": "FAILED", "message": "Mall missing."},
            {"field": "brand", "blocking": True, "status": "FAILED", "message": "Brand missing."},
        ]
        result = await api_submission_node(_confirmed_state(validation_errors=errors))
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_blocking_error_message_mentions_validation(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        errors = [{"field": "mall", "blocking": True, "status": "FAILED", "message": "Required."}]
        result = await api_submission_node(_confirmed_state(validation_errors=errors))
        assert "validation" in result["response_message"].lower()

    @pytest.mark.asyncio
    async def test_error_without_blocking_key_is_treated_as_blocking(self) -> None:
        """Errors missing the 'blocking' key are treated conservatively as blocking."""
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        errors = [{"field": "city", "status": "FAILED", "message": "City missing."}]
        result = await api_submission_node(_confirmed_state(validation_errors=errors))
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_empty_validation_errors_allow_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state(validation_errors=[]))
        assert result["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# TestApiSubmissionNodePayloadGuard
# ---------------------------------------------------------------------------


class TestApiSubmissionNodePayloadGuard:
    @pytest.mark.asyncio
    async def test_missing_create_payload_blocks_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        del state["backend_refs"]["create_payload"]
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_empty_backend_refs_blocks_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["backend_refs"] = {}
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_backend_refs_key_blocks_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        del state["backend_refs"]
        result = await api_submission_node(state)
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_missing_payload_message_mentions_payload(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        state = _confirmed_state()
        state["backend_refs"] = {}
        result = await api_submission_node(state)
        msg = result["response_message"].lower()
        assert "payload" in msg or "blocked" in msg


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeApiFailure
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeApiFailure:
    @pytest.mark.asyncio
    async def test_api_500_sets_status_failed(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService(
            force_error="Internal Server Error", force_status_code=500
        )
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_api_failure_service_request_status_is_failed(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService(force_error="Connection refused")
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["backend_refs"]["service_request_status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_api_failure_no_sr_id_in_backend_refs(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService(force_error="Timeout")
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert "sr_id" not in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_api_failure_response_message_is_user_friendly(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService(force_error="Gateway timeout")
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        msg = result["response_message"]
        assert len(msg) > 10
        assert "unable" in msg.lower() or "error" in msg.lower() or "failed" in msg.lower()

    @pytest.mark.asyncio
    async def test_api_failure_error_detail_in_response_message(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        error_text = "Database connection lost"
        mock_svc = MockServiceRequestAPIService(force_error=error_text)
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert error_text in result["response_message"]

    @pytest.mark.asyncio
    async def test_api_failure_workflow_stage_not_updated(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService(force_error="API down")
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert "workflow_stage" not in result


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeTracing
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeTracing:
    def _make_trace_manager(self) -> MagicMock:
        session = AsyncMock()
        session.add = MagicMock()   # synchronous, as SQLAlchemy Session.add is
        session.flush = AsyncMock()
        tm = MagicMock()
        tm.start_run = AsyncMock(return_value="mock-run-id")
        tm.capture_state_snapshot = AsyncMock()
        tm.capture_tool_call = AsyncMock()
        tm.finish_run = AsyncMock()
        tm._session = session
        return tm

    @pytest.mark.asyncio
    async def test_start_run_called_when_trace_manager_present(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)
        tm.start_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_tool_call_called_on_success(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)
        tm.capture_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_finish_run_called_on_success(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)
        tm.finish_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_state_snapshot_called_with_redacted_payload(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        payload = _make_payload()
        # Inject a sensitive key to verify redaction.
        payload["token"] = "super-secret-token"
        state = _confirmed_state(payload=payload)
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)

        # The snapshot call should have been made.
        tm.capture_state_snapshot.assert_called_once()
        _call_kwargs = tm.capture_state_snapshot.call_args
        snapshot_state = _call_kwargs.kwargs.get("state") or _call_kwargs[1].get("state")
        # The sensitive token must be redacted.
        assert snapshot_state is not None
        assert snapshot_state.get("token") == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_no_tracing_when_trace_manager_absent(self) -> None:
        """Node must not raise when trace_manager is absent."""
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            result = await api_submission_node(_confirmed_state())
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_tool_call_records_status_code(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)

        call_kwargs = tm.capture_tool_call.call_args.kwargs
        assert call_kwargs["status_code"] == 201

    @pytest.mark.asyncio
    async def test_tool_call_success_true_on_success(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm = self._make_trace_manager()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ):
            await api_submission_node(state)

        call_kwargs = tm.capture_tool_call.call_args.kwargs
        assert call_kwargs["success"] is True


# ---------------------------------------------------------------------------
# TestApiSubmissionNodeAuditLog
# ---------------------------------------------------------------------------


class TestApiSubmissionNodeAuditLog:
    def _make_trace_manager_with_session(self) -> tuple[MagicMock, MagicMock]:
        session = AsyncMock()
        session.add = MagicMock()   # synchronous, as SQLAlchemy Session.add is
        session.flush = AsyncMock()
        tm = MagicMock()
        tm.start_run = AsyncMock(return_value="mock-run-id")
        tm.capture_state_snapshot = AsyncMock()
        tm.capture_tool_call = AsyncMock()
        tm.finish_run = AsyncMock()
        tm._session = session
        return tm, session

    @pytest.mark.asyncio
    async def test_audit_log_written_on_success(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm, session = self._make_trace_manager_with_session()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ), patch(
            "app.agents.graph.nodes.api_submission_node.AuditLogRepository",
        ) as MockRepo:
            mock_repo_instance = AsyncMock()
            MockRepo.return_value = mock_repo_instance
            result = await api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        mock_repo_instance.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_log_action_is_service_request_created(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm, _ = self._make_trace_manager_with_session()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ), patch(
            "app.agents.graph.nodes.api_submission_node.AuditLogRepository",
        ) as MockRepo:
            mock_repo_instance = AsyncMock()
            MockRepo.return_value = mock_repo_instance
            await api_submission_node(state)

        call_kwargs = mock_repo_instance.create.call_args.kwargs
        assert call_kwargs["action"] == "service_request.created"

    @pytest.mark.asyncio
    async def test_audit_log_not_written_without_trace_manager(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ), patch(
            "app.agents.graph.nodes.api_submission_node.AuditLogRepository",
        ) as MockRepo:
            result = await api_submission_node(_confirmed_state())

        MockRepo.assert_not_called()
        assert result["status"] == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_audit_log_failure_does_not_abort_submission(self) -> None:
        from app.agents.graph.nodes.api_submission_node import api_submission_node

        tm, _ = self._make_trace_manager_with_session()
        state = _confirmed_state()
        state["trace_manager"] = tm
        state["trace_id"] = "550e8400-e29b-41d4-a716-446655440001"

        mock_svc = MockServiceRequestAPIService()
        with patch(
            "app.agents.graph.nodes.api_submission_node.get_service_request_api_service",
            return_value=mock_svc,
        ), patch(
            "app.agents.graph.nodes.api_submission_node.AuditLogRepository",
        ) as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.create.side_effect = RuntimeError("DB unavailable")
            MockRepo.return_value = mock_repo_instance
            result = await api_submission_node(state)

        # Audit log failure must not abort the successful submission.
        assert result["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# TestServiceRequestCreationResult
# ---------------------------------------------------------------------------


class TestServiceRequestCreationResult:
    def test_success_result_shape(self) -> None:
        r = ServiceRequestCreationResult(
            sr_id="SR-001",
            endpoint="https://api.example.com/service-requests",
            request_payload={"key": "value"},
            response_payload={"id": "SR-001"},
            latency_ms=120,
            status_code=201,
            correlation_id="corr-001",
        )
        assert r.sr_id == "SR-001"
        assert r.error is None
        assert r.latency_ms == 120

    def test_failure_result_shape(self) -> None:
        r = ServiceRequestCreationResult(
            sr_id=None,
            endpoint="https://api.example.com/service-requests",
            request_payload={},
            response_payload=None,
            latency_ms=50,
            status_code=500,
            error="Internal Server Error",
        )
        assert r.sr_id is None
        assert r.error == "Internal Server Error"
        assert r.correlation_id is None


# ---------------------------------------------------------------------------
# TestMockServiceRequestAPIService
# ---------------------------------------------------------------------------


class TestMockServiceRequestAPIService:
    @pytest.mark.asyncio
    async def test_create_returns_result_type(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({"test": "payload"})
        assert isinstance(result, ServiceRequestCreationResult)

    @pytest.mark.asyncio
    async def test_create_success_has_sr_id(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({})
        assert result.sr_id is not None
        assert len(result.sr_id) > 0

    @pytest.mark.asyncio
    async def test_create_success_status_code_201(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({})
        assert result.status_code == 201

    @pytest.mark.asyncio
    async def test_create_success_no_error(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({})
        assert result.error is None

    @pytest.mark.asyncio
    async def test_create_success_has_correlation_id(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({})
        assert result.correlation_id is not None

    @pytest.mark.asyncio
    async def test_create_with_force_error_returns_error(self) -> None:
        svc = MockServiceRequestAPIService(force_error="Connection refused")
        result = await svc.create_service_request({})
        assert result.sr_id is None
        assert result.error == "Connection refused"

    @pytest.mark.asyncio
    async def test_create_with_force_error_status_code_500(self) -> None:
        svc = MockServiceRequestAPIService(force_error="Timeout")
        result = await svc.create_service_request({})
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_created_requests_records_payload(self) -> None:
        svc = MockServiceRequestAPIService()
        payload = {"test": "data"}
        await svc.create_service_request(payload)
        assert len(svc.created_requests) == 1
        assert svc.created_requests[0]["payload"] == payload

    @pytest.mark.asyncio
    async def test_multiple_creates_tracked(self) -> None:
        svc = MockServiceRequestAPIService()
        await svc.create_service_request({"a": 1})
        await svc.create_service_request({"b": 2})
        assert len(svc.created_requests) == 2

    @pytest.mark.asyncio
    async def test_patch_raises_not_implemented(self) -> None:
        svc = MockServiceRequestAPIService()
        with pytest.raises(NotImplementedError):
            await svc.patch_service_request("SR-001", {})

    @pytest.mark.asyncio
    async def test_submit_report_raises_not_implemented(self) -> None:
        svc = MockServiceRequestAPIService()
        with pytest.raises(NotImplementedError):
            await svc.submit_report({})

    def test_is_abstract_subtype(self) -> None:
        svc = MockServiceRequestAPIService()
        assert isinstance(svc, AbstractServiceRequestAPIService)

    @pytest.mark.asyncio
    async def test_latency_ms_is_non_negative(self) -> None:
        svc = MockServiceRequestAPIService(simulated_latency_ms=42)
        result = await svc.create_service_request({})
        assert result.latency_ms == 42

    @pytest.mark.asyncio
    async def test_endpoint_uses_mock_scheme(self) -> None:
        svc = MockServiceRequestAPIService()
        result = await svc.create_service_request({})
        assert result.endpoint.startswith("mock://")


# ---------------------------------------------------------------------------
# TestHttpServiceRequestAPIService
# ---------------------------------------------------------------------------


def _make_http_client_ctx(response: MagicMock) -> MagicMock:
    """Return a mock for ``httpx.AsyncClient`` context manager."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_http_response(
    status_code: int = 201,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError("no body")
        resp.text = ""
    return resp


class TestHttpServiceRequestAPIService:
    @pytest.mark.asyncio
    async def test_201_response_returns_sr_id(self) -> None:
        body = {"id": "SR-HTTP-001", "status": "SUBMITTED"}
        resp = _make_http_response(201, body)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({"payload": {}})
        assert result.sr_id == "SR-HTTP-001"
        assert result.status_code == 201
        assert result.error is None

    @pytest.mark.asyncio
    async def test_200_response_also_accepted(self) -> None:
        body = {"id": "SR-HTTP-200", "status": "SUBMITTED"}
        resp = _make_http_response(200, body)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert result.sr_id == "SR-HTTP-200"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_correlation_id_from_header(self) -> None:
        body = {"id": "SR-001"}
        resp = _make_http_response(201, body, headers={"x-correlation-id": "hdr-corr-001"})
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert result.correlation_id == "hdr-corr-001"

    @pytest.mark.asyncio
    async def test_correlation_id_from_body_when_no_header(self) -> None:
        body = {"id": "SR-001", "correlation_id": "body-corr-002"}
        resp = _make_http_response(201, body)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert result.correlation_id == "body-corr-002"

    @pytest.mark.asyncio
    async def test_500_returns_error(self) -> None:
        resp = _make_http_response(500, None)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert result.sr_id is None
        assert "500" in (result.error or "")

    @pytest.mark.asyncio
    async def test_404_returns_error(self) -> None:
        resp = _make_http_response(404, None)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert result.sr_id is None
        assert "404" in (result.error or "")

    @pytest.mark.asyncio
    async def test_connection_error_returns_none_status_code(self) -> None:
        import httpx as _httpx

        client = AsyncMock()
        client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=ctx):
            result = await svc.create_service_request({})
        assert result.status_code is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_latency_ms_is_non_negative(self) -> None:
        body = {"id": "SR-001"}
        resp = _make_http_response(201, body)
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with patch("httpx.AsyncClient", return_value=_make_http_client_ctx(resp)):
            result = await svc.create_service_request({})
        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_patch_raises_not_implemented(self) -> None:
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with pytest.raises(NotImplementedError):
            await svc.patch_service_request("SR-001", {})

    @pytest.mark.asyncio
    async def test_submit_report_raises_not_implemented(self) -> None:
        svc = HttpServiceRequestAPIService(base_url="http://api.example.com")
        with pytest.raises(NotImplementedError):
            await svc.submit_report({})

    def test_extract_sr_id_from_top_level_id(self) -> None:
        svc = HttpServiceRequestAPIService.__new__(HttpServiceRequestAPIService)
        assert svc._extract_sr_id({"id": "SR-001"}) == "SR-001"

    def test_extract_sr_id_from_sr_id_key(self) -> None:
        svc = HttpServiceRequestAPIService.__new__(HttpServiceRequestAPIService)
        assert svc._extract_sr_id({"sr_id": "SR-002"}) == "SR-002"

    def test_extract_sr_id_from_nested_data(self) -> None:
        svc = HttpServiceRequestAPIService.__new__(HttpServiceRequestAPIService)
        assert svc._extract_sr_id({"data": {"id": "SR-003"}}) == "SR-003"

    def test_extract_sr_id_returns_none_when_absent(self) -> None:
        svc = HttpServiceRequestAPIService.__new__(HttpServiceRequestAPIService)
        assert svc._extract_sr_id({"status": "ok"}) is None

    def test_extract_sr_id_returns_none_for_non_dict(self) -> None:
        svc = HttpServiceRequestAPIService.__new__(HttpServiceRequestAPIService)
        assert svc._extract_sr_id(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestGetServiceRequestApiServiceFactory
# ---------------------------------------------------------------------------


class TestGetServiceRequestApiServiceFactory:
    def test_returns_mock_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.agents.services.service_request_api_service.settings",
            MagicMock(service_request_api_base_url=None),
        )
        svc = get_service_request_api_service()
        assert isinstance(svc, MockServiceRequestAPIService)

    def test_returns_http_when_base_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.agents.services.service_request_api_service.settings",
            MagicMock(service_request_api_base_url="https://api.example.com"),
        )
        svc = get_service_request_api_service()
        assert isinstance(svc, HttpServiceRequestAPIService)
