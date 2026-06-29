"""Unit tests for helper_schema — HelperIntent as str and ALL_INTENTS derivation.

Coverage
--------
- HelperSupervisorDecision accepts any string intent (not Literal-constrained)
- ALL_INTENTS includes all action_intents from all registered WorkflowConfigs
- ALL_INTENTS includes the shared read intents
- ADMIN role gets ALL_INTENTS
- MALL_MANAGER cannot trigger FM intents (RBAC gate unchanged)
- intents_for_roles returns correct union per role set
"""

from __future__ import annotations

import pytest

from app.agents.schemas.helper_schema import (
    ALL_INTENTS,
    ROLE_PERMITTED_INTENTS,
    HelperSupervisorDecision,
    _SR_READ_INTENTS,
    intents_for_roles,
)
from app.agents.registries.workflow_config import WORKFLOW_CONFIG_REGISTRY


# ---------------------------------------------------------------------------
# HelperIntent as str — accepts any intent string
# ---------------------------------------------------------------------------


class TestHelperIntentAsStr:
    def test_known_intent_accepted(self) -> None:
        decision = HelperSupervisorDecision(
            intent="CREATE_HANDOVER_SERVICE_REQUEST",
            confidence=0.95,
        )
        assert decision.intent == "CREATE_HANDOVER_SERVICE_REQUEST"

    def test_new_workflow_intent_accepted(self) -> None:
        """A brand-new intent not in the old Literal is now accepted."""
        decision = HelperSupervisorDecision(intent="CREATE_WORK_PERMIT", confidence=0.9)
        assert decision.intent == "CREATE_WORK_PERMIT"

    def test_ask_help_accepted(self) -> None:
        decision = HelperSupervisorDecision(intent="ASK_HELP", confidence=0.8)
        assert decision.intent == "ASK_HELP"

    def test_unknown_accepted(self) -> None:
        decision = HelperSupervisorDecision(intent="UNKNOWN", confidence=0.1)
        assert decision.intent == "UNKNOWN"

    def test_arbitrary_string_accepted(self) -> None:
        """Any string is valid — intent validation is done by RBAC, not type system."""
        decision = HelperSupervisorDecision(intent="COMPLETELY_NEW_INTENT_XYZ")
        assert decision.intent == "COMPLETELY_NEW_INTENT_XYZ"

    def test_default_confidence_is_one(self) -> None:
        decision = HelperSupervisorDecision(intent="ASK_HELP")
        assert decision.confidence == 1.0

    def test_optional_fields_default_to_none_or_empty(self) -> None:
        decision = HelperSupervisorDecision(intent="ASK_HELP")
        assert decision.service_category is None
        assert decision.sub_category is None
        assert decision.reasoning == ""


# ---------------------------------------------------------------------------
# ALL_INTENTS derived from registry
# ---------------------------------------------------------------------------


class TestAllIntentsDerived:
    def test_all_intents_includes_handover_action_intents(self) -> None:
        cfg = WORKFLOW_CONFIG_REGISTRY.get("handover_service_request_agent")
        assert cfg is not None
        for intent in cfg.action_intents:
            assert intent in ALL_INTENTS, f"{intent!r} missing from ALL_INTENTS"

    def test_all_intents_includes_read_intents(self) -> None:
        for intent in _SR_READ_INTENTS:
            assert intent in ALL_INTENTS, f"Read intent {intent!r} missing from ALL_INTENTS"

    def test_all_intents_is_superset_of_each_config_action_intents(self) -> None:
        for cfg in WORKFLOW_CONFIG_REGISTRY.values():
            assert cfg.action_intents <= ALL_INTENTS

    def test_all_intents_includes_ask_help(self) -> None:
        assert "ASK_HELP" in ALL_INTENTS

    def test_all_intents_includes_preview(self) -> None:
        assert "PREVIEW_SERVICE_REQUEST" in ALL_INTENTS


# ---------------------------------------------------------------------------
# ROLE_PERMITTED_INTENTS — security gate unchanged
# ---------------------------------------------------------------------------


class TestRolePermittedIntents:
    def test_admin_gets_all_intents(self) -> None:
        admin_intents = ROLE_PERMITTED_INTENTS.get("ADMIN", frozenset())
        assert ALL_INTENTS <= admin_intents

    def test_mall_manager_can_create_sr(self) -> None:
        mm = ROLE_PERMITTED_INTENTS.get("MALL_MANAGER", frozenset())
        assert "CREATE_HANDOVER_SERVICE_REQUEST" in mm

    def test_mall_manager_cannot_approve_fm(self) -> None:
        mm = ROLE_PERMITTED_INTENTS.get("MALL_MANAGER", frozenset())
        assert "APPROVE_HANDOVER_SERVICE_REQUEST" not in mm

    def test_fm_manager_can_approve(self) -> None:
        fm = ROLE_PERMITTED_INTENTS.get("FM_MANAGER", frozenset())
        assert "APPROVE_HANDOVER_SERVICE_REQUEST" in fm

    def test_fm_manager_cannot_create_sr(self) -> None:
        fm = ROLE_PERMITTED_INTENTS.get("FM_MANAGER", frozenset())
        assert "CREATE_HANDOVER_SERVICE_REQUEST" not in fm

    def test_all_roles_have_ask_help(self) -> None:
        for role, intents in ROLE_PERMITTED_INTENTS.items():
            if role == "ADMIN":
                continue
            assert "ASK_HELP" in intents, f"Role {role!r} missing ASK_HELP"


# ---------------------------------------------------------------------------
# intents_for_roles helper
# ---------------------------------------------------------------------------


class TestIntentsForRoles:
    def test_global_admin_gets_all_intents(self) -> None:
        result = intents_for_roles(frozenset({"MALL_MANAGER"}), is_global_admin=True)
        assert ALL_INTENTS <= result

    def test_mall_manager_role(self) -> None:
        result = intents_for_roles(frozenset({"MALL_MANAGER"}))
        assert "CREATE_HANDOVER_SERVICE_REQUEST" in result
        assert "ASK_HELP" in result

    def test_dd_engineer_role_has_read_intents(self) -> None:
        result = intents_for_roles(frozenset({"DD_ENGINEER"}))
        assert "ASK_HELP" in result
        assert "PREVIEW_SERVICE_REQUEST" in result

    def test_unknown_role_gets_read_intents(self) -> None:
        result = intents_for_roles(frozenset({"TOTALLY_UNKNOWN_ROLE"}))
        assert "ASK_HELP" in result
        assert "PREVIEW_SERVICE_REQUEST" in result

    def test_empty_roles_gets_read_intents(self) -> None:
        result = intents_for_roles(frozenset())
        assert "ASK_HELP" in result
