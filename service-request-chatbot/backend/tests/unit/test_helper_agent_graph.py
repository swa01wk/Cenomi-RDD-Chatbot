"""Unit tests for helper_agent_graph routing functions.

Coverage
--------
_route_after_sync:
  - FM_REVIEW → fm_review_entry
  - RDD_REVIEW → rdd_review_entry
  - SR_COMPLETED (terminal) → supervisor
  - SR_CREATED (terminal) → supervisor
  - Unknown stage with active_agent → _AGENT_ENTRY_NODES lookup
  - Unknown stage no active_agent → supervisor

_route_after_validation:
  - CREATE_SR all valid → confirmation
  - FM_REVIEW all valid → fm_confirmation
  - RDD_REVIEW all valid → rdd_confirmation
  - SR_COMPLETED (not a collection stage) → response_generation
  - Blocking error → missing_field

_route_after_supervisor:
  - ASK_HELP → faq_node
  - UNKNOWN → faq_node
  - CREATE_HANDOVER_SERVICE_REQUEST → registry
  - Unregistered intent → faq_node (safe fallback)
  - PREVIEW_SERVICE_REQUEST → preview
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.agents.graph.helper_agent_graph import (
    _route_after_sync,
    _route_after_validation,
    _route_after_supervisor,
    _SR_ACTION_INTENTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "test-session-001",
        "user_id": "test-user-001",
        "active_agent": "handover_service_request_agent",
        "workflow_stage": "CREATE_SR",
        "collected_data": {},
        "validation_errors": [],
        "status": "IN_PROGRESS",
        "intent": "CREATE_HANDOVER_SERVICE_REQUEST",
        "backend_refs": {},
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _route_after_sync
# ---------------------------------------------------------------------------


class TestRouteAfterSync:
    def test_fm_review_routes_to_fm_entry(self) -> None:
        state = _state(workflow_stage="FM_REVIEW")
        result = _route_after_sync(state)
        assert result == "fm_review_entry"

    def test_rdd_review_routes_to_rdd_entry(self) -> None:
        state = _state(workflow_stage="RDD_REVIEW")
        result = _route_after_sync(state)
        assert result == "rdd_review_entry"

    def test_sr_completed_routes_to_supervisor(self) -> None:
        state = _state(workflow_stage="SR_COMPLETED")
        result = _route_after_sync(state)
        assert result == "supervisor"

    def test_sr_created_routes_to_supervisor(self) -> None:
        state = _state(workflow_stage="SR_CREATED")
        result = _route_after_sync(state)
        assert result == "supervisor"

    def test_create_sr_with_active_agent_uses_entry_nodes(self) -> None:
        state = _state(workflow_stage="CREATE_SR", active_agent="handover_service_request_agent")
        result = _route_after_sync(state)
        # CREATE_SR is not in stage_sync_nodes; falls through to _AGENT_ENTRY_NODES
        assert result == "handover_entry"

    def test_unknown_stage_no_agent_falls_back_to_supervisor(self) -> None:
        state = _state(workflow_stage="UNKNOWN_STAGE", active_agent="")
        result = _route_after_sync(state)
        assert result == "supervisor"

    def test_empty_stage_no_agent_falls_back_to_supervisor(self) -> None:
        state = _state(workflow_stage="", active_agent="")
        result = _route_after_sync(state)
        assert result == "supervisor"


# ---------------------------------------------------------------------------
# _route_after_validation
# ---------------------------------------------------------------------------


class TestRouteAfterValidation:
    def _all_fields(self) -> dict[str, Any]:
        """Complete CREATE_SR collected_data."""
        return {
            "tenant_profile_id": "TP-001", "property_id": "PROP-001",
            "lease_code": "LC-001", "lease_id": "LEASE-001", "brand_id": "BR-001",
            "mall": "Test Mall", "brand": "Test Brand", "lease": "Lease A",
            "unit_codes": ["U-01"], "city": "Riyadh", "contracted_area": 150,
            "title": "handover-LC-001-test", "description": "Test",
            "startDate": "2026-07-01", "endDate": "2026-07-03",
            "inspection_done_by": "FM_MANAGER", "comments": "",
        }

    def test_blocking_error_routes_to_missing_field(self) -> None:
        state = _state(
            workflow_stage="CREATE_SR",
            validation_errors=[{"blocking": True, "field": "startDate", "validation_type": "date_range"}],
        )
        result = _route_after_validation(state)
        assert result == "missing_field"

    def test_create_sr_all_valid_routes_to_confirmation(self) -> None:
        state = _state(
            workflow_stage="CREATE_SR",
            collected_data=self._all_fields(),
            validation_errors=[],
        )
        result = _route_after_validation(state)
        assert result == "confirmation"

    def test_fm_review_all_valid_routes_to_fm_confirmation(self) -> None:
        state = _state(
            workflow_stage="FM_REVIEW",
            collected_data={"unit_readiness_date": "2026-07-10"},
            validation_errors=[],
        )
        result = _route_after_validation(state)
        assert result == "fm_confirmation"

    def test_rdd_review_all_valid_routes_to_rdd_confirmation(self) -> None:
        state = _state(
            workflow_stage="RDD_REVIEW",
            collected_data={
                "guideLineLink": "http://link", "actual_handover_date": "2026-07-15",
                "fitout_start_date": "2026-07-16", "fitout_end_date": "2026-07-20",
                "trading_date": "2026-07-25",
            },
            validation_errors=[],
        )
        result = _route_after_validation(state)
        assert result == "rdd_confirmation"

    def test_terminal_stage_routes_to_response_generation(self) -> None:
        state = _state(workflow_stage="SR_COMPLETED", validation_errors=[])
        result = _route_after_validation(state)
        assert result == "response_generation"

    def test_missing_fields_routes_to_missing_field(self) -> None:
        # Empty collected_data with CREATE_SR stage → missing fields present
        state = _state(workflow_stage="CREATE_SR", collected_data={}, validation_errors=[])
        result = _route_after_validation(state)
        assert result == "missing_field"

    def test_unknown_agent_falls_back_to_handover_defaults(self) -> None:
        """No active_agent → falls back to handover collection_stages."""
        state = _state(
            workflow_stage="CREATE_SR",
            active_agent="",
            collected_data=self._all_fields(),
            validation_errors=[],
        )
        result = _route_after_validation(state)
        assert result == "confirmation"


# ---------------------------------------------------------------------------
# _route_after_supervisor — HelperIntent as str
# ---------------------------------------------------------------------------


class TestRouteAfterSupervisor:
    def test_ask_help_routes_to_faq_node(self) -> None:
        state = _state(intent="ASK_HELP", status="IN_PROGRESS")
        result = _route_after_supervisor(state)
        assert result == "faq_node"

    def test_unknown_routes_to_faq_node(self) -> None:
        state = _state(intent="UNKNOWN", status="IN_PROGRESS")
        result = _route_after_supervisor(state)
        assert result == "faq_node"

    def test_create_handover_routes_to_registry(self) -> None:
        state = _state(intent="CREATE_HANDOVER_SERVICE_REQUEST", status="IN_PROGRESS")
        result = _route_after_supervisor(state)
        assert result == "registry"

    def test_preview_routes_to_preview(self) -> None:
        state = _state(intent="PREVIEW_SERVICE_REQUEST", status="IN_PROGRESS")
        result = _route_after_supervisor(state)
        assert result == "preview"

    def test_check_status_routes_to_preview(self) -> None:
        state = _state(intent="CHECK_SERVICE_REQUEST_STATUS", status="IN_PROGRESS")
        result = _route_after_supervisor(state)
        assert result == "preview"

    def test_unregistered_intent_routes_to_faq_fallback(self) -> None:
        """A brand-new intent not in any registry falls back to faq_node safely."""
        state = _state(intent="CREATE_WORK_PERMIT", status="IN_PROGRESS")
        # CREATE_WORK_PERMIT is not in _SR_ACTION_INTENTS yet (no work permit registered)
        result = _route_after_supervisor(state)
        # Should fall through to FAQ (safe fallback) since it's not an action intent
        assert result == "faq_node"

    def test_waiting_for_user_routes_to_response_generation(self) -> None:
        state = _state(intent="CREATE_HANDOVER_SERVICE_REQUEST", status="WAITING_FOR_USER")
        result = _route_after_supervisor(state)
        assert result == "response_generation"


# ---------------------------------------------------------------------------
# _SR_ACTION_INTENTS derived from registry
# ---------------------------------------------------------------------------


class TestSRActionIntentsDerived:
    def test_create_handover_is_action_intent(self) -> None:
        assert "CREATE_HANDOVER_SERVICE_REQUEST" in _SR_ACTION_INTENTS

    def test_approve_handover_is_action_intent(self) -> None:
        assert "APPROVE_HANDOVER_SERVICE_REQUEST" in _SR_ACTION_INTENTS

    def test_ask_help_is_not_action_intent(self) -> None:
        assert "ASK_HELP" not in _SR_ACTION_INTENTS

    def test_unknown_is_not_action_intent(self) -> None:
        assert "UNKNOWN" not in _SR_ACTION_INTENTS
