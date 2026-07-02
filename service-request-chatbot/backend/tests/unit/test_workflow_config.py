"""Unit tests for the WorkflowConfig registry.

Coverage
--------
- Registry shape and completeness for the handover agent
- stage_sync_nodes covers FM_REVIEW and RDD_REVIEW
- action_intents is non-empty and drives _SR_ACTION_INTENTS
- Unknown agent returns None
- register_workflow allows adding a second workflow
- Second workflow is independent from handover config
"""

from __future__ import annotations

import pytest

from app.agents.registries.workflow_config import (
    WORKFLOW_CONFIG_REGISTRY,
    WorkflowConfig,
    get_workflow_config,
    list_registered_workflows,
    register_workflow,
)
from app.agents.graph.help_agent_graph import _SR_ACTION_INTENTS


# ---------------------------------------------------------------------------
# Handover config — shape and completeness
# ---------------------------------------------------------------------------


class TestHandoverConfigRegistered:
    def test_handover_config_is_registered(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None

    def test_agent_name_matches_key(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert cfg.agent_name == "rdd_agent"

    def test_extraction_prompt_is_non_empty_string(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert isinstance(cfg.extraction_prompt, str)
        assert len(cfg.extraction_prompt) > 100

    def test_field_questions_is_dict(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert isinstance(cfg.field_questions, dict)
        assert len(cfg.field_questions) > 0

    def test_stage_sync_nodes_covers_fm_and_rdd(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert "FM_REVIEW" in cfg.stage_sync_nodes
        assert "RDD_REVIEW" in cfg.stage_sync_nodes
        assert cfg.stage_sync_nodes["FM_REVIEW"] == "fm_review_entry"
        assert cfg.stage_sync_nodes["RDD_REVIEW"] == "rdd_review_entry"

    def test_collection_stages_non_empty(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert len(cfg.collection_stages) > 0
        assert "CREATE_SR" in cfg.collection_stages

    def test_confirmation_nodes_per_stage(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert cfg.confirmation_nodes.get("CREATE_SR") == "confirmation"
        assert cfg.confirmation_nodes.get("FM_REVIEW") == "fm_confirmation"
        assert cfg.confirmation_nodes.get("RDD_REVIEW") == "rdd_confirmation"

    def test_terminal_stages_non_empty(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert "SR_CREATED" in cfg.terminal_stages
        assert "SR_COMPLETED" in cfg.terminal_stages

    def test_backend_fields_non_empty(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert "tenant_profile_id" in cfg.backend_fields
        assert "lease_id" in cfg.backend_fields

    def test_auto_generated_fields_contains_title(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert "title" in cfg.auto_generated_fields

    def test_lease_trigger_fields_non_empty(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert len(cfg.lease_trigger_fields) > 0
        assert "lease_code" in cfg.lease_trigger_fields

    def test_action_intents_non_empty(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        assert len(cfg.action_intents) > 0
        assert "CREATE_RDD_SERVICE_REQUEST" in cfg.action_intents


# ---------------------------------------------------------------------------
# Unknown agent returns None
# ---------------------------------------------------------------------------


class TestUnknownAgent:
    def test_unknown_agent_returns_none(self) -> None:
        assert get_workflow_config("does_not_exist") is None

    def test_none_agent_returns_none(self) -> None:
        assert get_workflow_config(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert get_workflow_config("") is None


# ---------------------------------------------------------------------------
# _SR_ACTION_INTENTS derived from registry
# ---------------------------------------------------------------------------


class TestSRActionIntentsDerived:
    def test_sr_action_intents_includes_handover_intents(self) -> None:
        cfg = get_workflow_config("rdd_agent")
        assert cfg is not None
        for intent in cfg.action_intents:
            assert intent in _SR_ACTION_INTENTS

    def test_sr_action_intents_is_union_of_all_action_intents(self) -> None:
        expected = frozenset(
            intent
            for cfg in WORKFLOW_CONFIG_REGISTRY.values()
            for intent in cfg.action_intents
        )
        assert _SR_ACTION_INTENTS == expected


# ---------------------------------------------------------------------------
# list_registered_workflows
# ---------------------------------------------------------------------------


class TestListRegisteredWorkflows:
    def test_returns_list(self) -> None:
        result = list_registered_workflows()
        assert isinstance(result, list)

    def test_handover_is_in_list(self) -> None:
        names = [cfg.agent_name for cfg in list_registered_workflows()]
        assert "rdd_agent" in names


# ---------------------------------------------------------------------------
# register_workflow — second workflow is independent
# ---------------------------------------------------------------------------


class TestRegisterWorkflow:
    def test_second_workflow_can_be_registered(self) -> None:
        mock_cfg = WorkflowConfig(
            agent_name="test_mock_agent",
            extraction_prompt="Mock prompt",
            field_questions={"mock_field": "What is the mock field?"},
            stage_sync_nodes={"MOCK_STAGE": "mock_entry"},
            collection_stages=frozenset({"MOCK_STAGE"}),
            confirmation_nodes={"MOCK_STAGE": "mock_confirmation"},
            terminal_stages=frozenset({"MOCK_DONE"}),
            backend_fields=frozenset(),
            auto_generated_fields=frozenset(),
            lease_trigger_fields=(),
            action_intents=frozenset({"CREATE_MOCK_REQUEST"}),
        )
        try:
            register_workflow(mock_cfg)
            assert get_workflow_config("test_mock_agent") is mock_cfg
        finally:
            # Clean up so the mock doesn't pollute other tests
            WORKFLOW_CONFIG_REGISTRY.pop("test_mock_agent", None)

    def test_second_workflow_does_not_affect_handover(self) -> None:
        mock_cfg = WorkflowConfig(
            agent_name="test_isolation_agent",
            extraction_prompt="Isolation prompt",
            field_questions={},
            stage_sync_nodes={},
            collection_stages=frozenset(),
            confirmation_nodes={},
            terminal_stages=frozenset(),
            backend_fields=frozenset(),
            auto_generated_fields=frozenset(),
            lease_trigger_fields=(),
            action_intents=frozenset({"CREATE_ISOLATION_TEST"}),
        )
        try:
            register_workflow(mock_cfg)
            handover_cfg = get_workflow_config("rdd_agent")
            assert handover_cfg is not None
            assert handover_cfg.agent_name == "rdd_agent"
            assert "CREATE_RDD_SERVICE_REQUEST" in handover_cfg.action_intents
        finally:
            WORKFLOW_CONFIG_REGISTRY.pop("test_isolation_agent", None)
