"""Unit tests — Supervisor routing decisions and Registry node.

All LLM calls are mocked via ``unittest.mock.AsyncMock`` so these tests run
without network access or an OpenAI API key.  The ``trace_manager`` slot is
intentionally left absent from state dicts to exercise the "no tracing"
code-path without setting up a real database.

Test groups
-----------
TestSupervisorDecisionModel      — Pydantic model validation
TestServiceRequestRegistry       — Registry helper functions
TestSupervisorSessionContinuity  — active_agent short-circuit logic
TestSupervisorRouting            — end-to-end routing decisions
TestSupervisorClarification      — low-confidence / UNKNOWN handling
TestSupervisorLLMFailure         — graceful degradation on parse errors
TestRegistryNode                 — registry_node routing and error paths
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.schemas.supervisor_schema import SupervisorDecision
from app.agents.registries.service_request_registry import (
    SERVICE_REQUEST_AGENT_REGISTRY,
    is_registered,
    list_registered_agents,
    lookup_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(
    intent: str = "CREATE_HANDOVER_SERVICE_REQUEST",
    confidence: float = 0.9,
    service_category: str | None = "FIT_OUT_AND_HANDOVER",
    sub_category: str | None = "HANDOVER",
    target_agent: str | None = "handover_service_request_agent",
    reasoning: str = "User wants to create a handover SR",
) -> SupervisorDecision:
    return SupervisorDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=confidence,
        service_category=service_category,
        sub_category=sub_category,
        target_agent=target_agent,
        reasoning=reasoning,
    )


def _base_state(**overrides: Any) -> dict[str, Any]:
    """Return a minimal state dict without trace_manager."""
    return {
        "session_id": "sess-001",
        "user_id": "user-001",
        "user_message": "I want to create a handover service request",
        **overrides,
    }


# ---------------------------------------------------------------------------
# SupervisorDecision model
# ---------------------------------------------------------------------------


class TestSupervisorDecisionModel:
    def test_valid_create_intent(self) -> None:
        d = _make_decision()
        assert d.intent == "CREATE_HANDOVER_SERVICE_REQUEST"
        assert d.confidence == 0.9
        assert d.service_category == "FIT_OUT_AND_HANDOVER"
        assert d.sub_category == "HANDOVER"
        assert d.target_agent == "handover_service_request_agent"

    def test_valid_unknown_intent(self) -> None:
        d = _make_decision(
            intent="UNKNOWN",
            confidence=0.2,
            service_category=None,
            sub_category=None,
            target_agent=None,
        )
        assert d.intent == "UNKNOWN"
        assert d.service_category is None

    def test_all_valid_intents(self) -> None:
        valid_intents = [
            "CREATE_HANDOVER_SERVICE_REQUEST",
            "UPDATE_HANDOVER_SERVICE_REQUEST",
            "APPROVE_HANDOVER_SERVICE_REQUEST",
            "CHECK_SERVICE_REQUEST_STATUS",
            "UNKNOWN",
        ]
        for intent in valid_intents:
            d = _make_decision(intent=intent)
            assert d.intent == intent

    def test_confidence_clamped_lower(self) -> None:
        with pytest.raises(Exception):
            _make_decision(confidence=-0.1)

    def test_confidence_clamped_upper(self) -> None:
        with pytest.raises(Exception):
            _make_decision(confidence=1.1)

    def test_reasoning_required(self) -> None:
        with pytest.raises(Exception):
            SupervisorDecision(
                intent="UNKNOWN",
                confidence=0.5,
                # reasoning missing
            )

    def test_optional_fields_default_none(self) -> None:
        d = SupervisorDecision(
            intent="UNKNOWN",
            confidence=0.3,
            reasoning="not sure",
        )
        assert d.service_category is None
        assert d.sub_category is None
        assert d.target_agent is None

    def test_model_dump_round_trip(self) -> None:
        d = _make_decision()
        data = d.model_dump()
        restored = SupervisorDecision.model_validate(data)
        assert restored == d


# ---------------------------------------------------------------------------
# Service Request Registry
# ---------------------------------------------------------------------------


class TestServiceRequestRegistry:
    def test_registry_structure(self) -> None:
        assert "FIT_OUT_AND_HANDOVER" in SERVICE_REQUEST_AGENT_REGISTRY
        assert "HANDOVER" in SERVICE_REQUEST_AGENT_REGISTRY["FIT_OUT_AND_HANDOVER"]

    def test_handover_agent_config(self) -> None:
        cfg = SERVICE_REQUEST_AGENT_REGISTRY["FIT_OUT_AND_HANDOVER"]["HANDOVER"]
        assert cfg["agent_name"] == "handover_service_request_agent"
        assert cfg["display_name"] == "Handover Service Request Agent"
        assert cfg["schema_key"] == "handover_service_request_schema"

    def test_lookup_agent_found(self) -> None:
        cfg = lookup_agent("FIT_OUT_AND_HANDOVER", "HANDOVER")
        assert cfg is not None
        assert cfg["agent_name"] == "handover_service_request_agent"

    def test_lookup_agent_missing_category(self) -> None:
        assert lookup_agent("UNKNOWN_CATEGORY", "HANDOVER") is None

    def test_lookup_agent_missing_subcategory(self) -> None:
        assert lookup_agent("FIT_OUT_AND_HANDOVER", "NONEXISTENT") is None

    def test_lookup_agent_empty_strings(self) -> None:
        assert lookup_agent("", "") is None

    def test_is_registered_true(self) -> None:
        assert is_registered("FIT_OUT_AND_HANDOVER", "HANDOVER") is True

    def test_is_registered_false(self) -> None:
        assert is_registered("FIT_OUT_AND_HANDOVER", "FITTING_ROOMS") is False

    def test_list_registered_agents_returns_all(self) -> None:
        agents = list_registered_agents()
        names = [a["agent_name"] for a in agents]
        assert "handover_service_request_agent" in names

    def test_list_registered_agents_non_empty(self) -> None:
        assert len(list_registered_agents()) >= 1


# ---------------------------------------------------------------------------
# Supervisor — session continuity
# ---------------------------------------------------------------------------


class TestSupervisorSessionContinuity:
    """When active_agent is set and the user is not cancelling, the supervisor
    should return immediately without calling the LLM."""

    @pytest.mark.asyncio
    async def test_active_agent_returned_unchanged(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        state = _base_state(
            active_agent="handover_service_request_agent",
            user_message="What's next?",
        )

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await supervisor_node(state)

        mock_llm.assert_not_called()
        assert result["active_agent"] == "handover_service_request_agent"

    @pytest.mark.asyncio
    async def test_cancel_phrase_triggers_reclassification(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="CREATE_HANDOVER_SERVICE_REQUEST",
            confidence=0.85,
        )

        state = _base_state(
            active_agent="handover_service_request_agent",
            user_message="cancel, I want to start over with a different request",
        )

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 50, 30, 120),
        ) as mock_llm, patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        mock_llm.assert_called_once()
        assert result.get("intent") == "CREATE_HANDOVER_SERVICE_REQUEST"

    @pytest.mark.asyncio
    async def test_nevermind_triggers_reclassification(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(intent="UNKNOWN", confidence=0.1)
        state = _base_state(
            active_agent="handover_service_request_agent",
            user_message="nevermind",
        )

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 10, 10, 50),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        # Low confidence / UNKNOWN → clarification
        assert result.get("status") == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_no_active_agent_always_classifies(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision()
        state = _base_state(user_message="I need to raise a handover SR")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 60, 40, 100),
        ) as mock_llm, patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            await supervisor_node(state)

        mock_llm.assert_called_once()


# ---------------------------------------------------------------------------
# Supervisor — routing decisions
# ---------------------------------------------------------------------------


class TestSupervisorRouting:
    @pytest.mark.asyncio
    async def test_create_handover_routes_correctly(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision()
        state = _base_state(user_message="I want to raise a handover service request")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 80, 60, 200),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["intent"] == "CREATE_HANDOVER_SERVICE_REQUEST"
        assert result["service_category"] == "FIT_OUT_AND_HANDOVER"
        assert result["sub_category"] == "HANDOVER"
        assert result["active_agent"] == "handover_service_request_agent"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_routing_does_not_include_form_fields(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision()
        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 80, 60, 200),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        # Supervisor must NOT write form fields
        for field_name in (
            "title", "description", "startDate", "endDate",
            "lease_code", "mall", "comments",
        ):
            assert field_name not in result, (
                f"Supervisor must not set form field '{field_name}'"
            )

    @pytest.mark.asyncio
    async def test_update_intent_routes_without_agent(self) -> None:
        """UPDATE intent has no registered agent yet; routing still proceeds."""
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="UPDATE_HANDOVER_SERVICE_REQUEST",
            confidence=0.8,
            service_category=None,
            sub_category=None,
            target_agent=None,
        )
        state = _base_state(user_message="Update my handover SR title")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 70, 50, 150),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["intent"] == "UPDATE_HANDOVER_SERVICE_REQUEST"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_check_status_intent(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="CHECK_SERVICE_REQUEST_STATUS",
            confidence=0.85,
            service_category=None,
            sub_category=None,
            target_agent=None,
        )
        state = _base_state(user_message="What is the status of SR-1234?")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 60, 40, 120),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["intent"] == "CHECK_SERVICE_REQUEST_STATUS"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_approve_intent(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="APPROVE_HANDOVER_SERVICE_REQUEST",
            confidence=0.9,
            service_category=None,
            sub_category=None,
            target_agent=None,
        )
        state = _base_state(user_message="Approve the handover for unit 101")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 60, 40, 120),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["intent"] == "APPROVE_HANDOVER_SERVICE_REQUEST"
        assert result["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Supervisor — clarification path
# ---------------------------------------------------------------------------


class TestSupervisorClarification:
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_clarification(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="CREATE_HANDOVER_SERVICE_REQUEST",
            confidence=0.4,  # below threshold of 0.6
        )
        state = _base_state(user_message="I need some help")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 30, 20, 80),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert "response_message" in result
        assert result["response_message"]  # non-empty

    @pytest.mark.asyncio
    async def test_unknown_intent_triggers_clarification(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(
            intent="UNKNOWN",
            confidence=0.9,  # high confidence that it's unknown
            service_category=None,
            sub_category=None,
            target_agent=None,
        )
        state = _base_state(user_message="hello there")

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 20, 10, 60),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["status"] == "WAITING_FOR_USER"

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_proceeds(self) -> None:
        """confidence == threshold should still route (not clarify)."""
        from app.agents.graph.nodes.supervisor_node import supervisor_node
        from app.agents.prompts.supervisor_prompt import CONFIDENCE_THRESHOLD

        decision = _make_decision(confidence=CONFIDENCE_THRESHOLD)
        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 50, 30, 100),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        # Exactly at threshold → clarification (strict less-than check)
        # CONFIDENCE_THRESHOLD is 0.6; confidence 0.6 is NOT below threshold.
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_just_below_threshold_asks_clarification(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        decision = _make_decision(confidence=0.59)
        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            return_value=(decision, 50, 30, 100),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["status"] == "WAITING_FOR_USER"


# ---------------------------------------------------------------------------
# Supervisor — LLM failure / graceful degradation
# ---------------------------------------------------------------------------


class TestSupervisorLLMFailure:
    @pytest.mark.asyncio
    async def test_json_decode_error_returns_fallback_message(self) -> None:
        import json
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            side_effect=json.JSONDecodeError("bad json", "", 0),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert "response_message" in result

    @pytest.mark.asyncio
    async def test_generic_exception_returns_fallback_message(self) -> None:
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network timeout"),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            result = await supervisor_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert result.get("response_message")

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_raise(self) -> None:
        """A failing LLM call must never propagate an exception from supervisor_node."""
        from app.agents.graph.nodes.supervisor_node import supervisor_node

        state = _base_state()

        with patch(
            "app.agents.graph.nodes.supervisor_node._call_supervisor_llm",
            new_callable=AsyncMock,
            side_effect=Exception("critical failure"),
        ), patch(
            "app.agents.graph.nodes.supervisor_node.get_default_gateway",
            return_value=MagicMock(),
        ):
            # Should NOT raise
            result = await supervisor_node(state)

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Registry node
# ---------------------------------------------------------------------------


class TestRegistryNode:
    @pytest.mark.asyncio
    async def test_valid_routing_resolves_agent(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(
            service_category="FIT_OUT_AND_HANDOVER",
            sub_category="HANDOVER",
            active_agent="handover_service_request_agent",
        )
        result = await registry_node(state)

        assert result["active_agent"] == "handover_service_request_agent"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_missing_service_category_returns_clarification(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(service_category=None, sub_category="HANDOVER")
        result = await registry_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert "response_message" in result

    @pytest.mark.asyncio
    async def test_missing_sub_category_returns_clarification(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(service_category="FIT_OUT_AND_HANDOVER", sub_category=None)
        result = await registry_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert "response_message" in result

    @pytest.mark.asyncio
    async def test_unknown_routing_returns_clarification(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(
            service_category="UNKNOWN_CATEGORY",
            sub_category="UNKNOWN_SUB",
        )
        result = await registry_node(state)

        assert result["status"] == "WAITING_FOR_USER"
        assert "response_message" in result

    @pytest.mark.asyncio
    async def test_registry_overrides_mismatched_supervisor_agent(self) -> None:
        """Registry is authoritative — it should override a wrong supervisor choice."""
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(
            service_category="FIT_OUT_AND_HANDOVER",
            sub_category="HANDOVER",
            active_agent="wrong_agent_name",  # supervisor mismatch
        )
        result = await registry_node(state)

        assert result["active_agent"] == "handover_service_request_agent"
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_registry_node_does_not_include_form_fields(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(
            service_category="FIT_OUT_AND_HANDOVER",
            sub_category="HANDOVER",
        )
        result = await registry_node(state)

        for field_name in ("title", "description", "startDate", "lease_code"):
            assert field_name not in result

    @pytest.mark.asyncio
    async def test_registry_node_no_active_agent_in_state(self) -> None:
        from app.agents.graph.nodes.registry_node import registry_node

        state = _base_state(
            service_category="FIT_OUT_AND_HANDOVER",
            sub_category="HANDOVER",
        )
        result = await registry_node(state)

        assert result["active_agent"] == "handover_service_request_agent"
        assert result["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Cross-cutting: registry exported constant matches node export
# ---------------------------------------------------------------------------


class TestRegistryExport:
    def test_registry_node_re_exports_registry_constant(self) -> None:
        from app.agents.graph.nodes.registry_node import SERVICE_REQUEST_AGENT_REGISTRY
        from app.agents.registries.service_request_registry import (
            SERVICE_REQUEST_AGENT_REGISTRY as SOURCE,
        )

        assert SERVICE_REQUEST_AGENT_REGISTRY is SOURCE

    def test_confidence_threshold_is_float(self) -> None:
        from app.agents.prompts.supervisor_prompt import CONFIDENCE_THRESHOLD

        assert isinstance(CONFIDENCE_THRESHOLD, float)
        assert 0.0 < CONFIDENCE_THRESHOLD < 1.0
