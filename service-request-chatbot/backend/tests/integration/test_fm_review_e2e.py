"""Integration tests for the FM_REVIEW end-to-end flow.

Covers the full FM_REVIEW pipeline:
  document_upload_node → merge_state_node → fm_payload_builder_node → fm_api_submission_node

Scenarios
---------
1. 3 FM documents → bridge → payload includes all 3 doc IDs
2. expected_handover_date auto-computed in merge_state and carried into FM payload
3. PATCH called with document IDs and dates; fm_status=APPROVED on success
4. Save-progress path uses IN_PROCESS status
5. Wrong role (MALL_MANAGER) attempting FM approval → permission denied
6. Chained full path: doc upload + merge (with auto-calc) + payload + submission
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph.nodes.document_upload_node import document_upload_node
from app.agents.graph.nodes.handover.fm_api_submission_node import fm_api_submission_node
from app.agents.graph.nodes.handover.fm_payload_builder_node import fm_payload_builder_node
from app.agents.graph.nodes.handover.fm_review_entry_node import fm_review_entry_node
from app.agents.graph.nodes.handover.merge_state_node import merge_state_node
from app.agents.services.service_request_api_service import ServiceRequestCreationResult
from app.types.chat import AuthContext


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _fm_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="fm_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["FM_MANAGER"],
    )


def _mall_manager_auth() -> AuthContext:
    from app.agents.services.permission_service import ROLE_PERMISSION_MAP
    return AuthContext(
        subject_id="mm_user",
        tenant_id=None,
        roles=ROLE_PERMISSION_MAP["MALL_MANAGER"],
    )


def _base_fm_state(**kwargs: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "session_id": "fm-integ-sess-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "validation_errors": [],
        "collected_data": {"unit_readiness_date": "2026-06-18"},
        "backend_refs": {
            "sr_id": "sr-fm-001",
            "user_role": "FM_MANAGER",
            "create_payload": {
                "payload": {
                    "mall": "Dubai Mall",
                    "brand": "BrandX",
                    "lease": "LC-001",
                    "title": "FM Integration Test SR",
                    "tenant_profile_id": 116,
                    "property_id": 10,
                },
                "lease_id": 456,
            },
            "sr_operations": [],
        },
        "documents": [
            {"document_id": "fm-doc-checklist", "document_type_id": "SR_HANDOVER_CHECKLIST"},
            {"document_id": "fm-doc-survey", "document_type_id": "SR_HANDOVER_SITE_SURVEY"},
            {"document_id": "fm-doc-cop", "document_type_id": "SR_COP_CHECKLIST_OTHER"},
        ],
        "workflow_stage": "FM_REVIEW",
        "action_override": None,
        "auth": _fm_auth(),
    }
    state.update(kwargs)
    return state


def _mock_patch_success(sr_id: str = "sr-fm-001") -> ServiceRequestCreationResult:
    return ServiceRequestCreationResult(
        sr_id=sr_id,
        endpoint=f"mock://service-requests/{sr_id}",
        request_payload={},
        response_payload={"success": True, "id": sr_id},
        latency_ms=10,
        status_code=200,
    )


# ---------------------------------------------------------------------------
# document_upload_node in FM context
# ---------------------------------------------------------------------------


class TestFMDocumentBridge:
    @pytest.mark.asyncio
    async def test_three_fm_docs_all_in_uploaded_documents(self) -> None:
        state = _base_fm_state()
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert "fm-doc-checklist" in uploaded
        assert "fm-doc-survey" in uploaded
        assert "fm-doc-cop" in uploaded
        assert len(uploaded) == 3

    @pytest.mark.asyncio
    async def test_doc_bridge_does_not_set_rdd_document_id(self) -> None:
        state = _base_fm_state()
        result = await document_upload_node(state)
        assert "rdd_document_id" not in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_doc_bridge_merges_with_existing_docs(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["uploaded_documents"] = ["pre-existing-doc"]
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert "pre-existing-doc" in uploaded
        assert "fm-doc-checklist" in uploaded


# ---------------------------------------------------------------------------
# merge_state_node with FM_REVIEW auto-calc
# ---------------------------------------------------------------------------


class TestFMMergeStateWithAutoCalc:
    @pytest.mark.asyncio
    async def test_expected_handover_date_auto_computed(self) -> None:
        state = _base_fm_state()
        result = await merge_state_node(state)
        assert result["collected_data"]["expected_handover_date"] == "2026-06-25"

    @pytest.mark.asyncio
    async def test_unit_readiness_date_preserved(self) -> None:
        state = _base_fm_state()
        result = await merge_state_node(state)
        assert result["collected_data"]["unit_readiness_date"] == "2026-06-18"


# ---------------------------------------------------------------------------
# fm_payload_builder_node with docs and auto-computed date
# ---------------------------------------------------------------------------


class TestFMPayloadWithDocuments:
    @pytest.mark.asyncio
    async def test_payload_includes_all_three_doc_ids(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["uploaded_documents"] = [
            "fm-doc-checklist", "fm-doc-survey", "fm-doc-cop"
        ]
        state["backend_refs"]["fm_action"] = "approve"
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        result = await fm_payload_builder_node(state)
        payload_inner = result["backend_refs"]["fm_payload"]["payload"]

        for doc_id in ("fm-doc-checklist", "fm-doc-survey", "fm-doc-cop"):
            assert doc_id in payload_inner["documents_ids"]

    @pytest.mark.asyncio
    async def test_payload_includes_unit_readiness_date(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["fm_action"] = "save_progress"
        state["backend_refs"]["uploaded_documents"] = ["fm-doc-checklist"]
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        result = await fm_payload_builder_node(state)
        payload_inner = result["backend_refs"]["fm_payload"]["payload"]
        assert payload_inner["unit_readiness_date"] == "2026-06-18"

    @pytest.mark.asyncio
    async def test_payload_includes_expected_handover_date(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["fm_action"] = "save_progress"
        state["backend_refs"]["uploaded_documents"] = ["fm-doc-checklist"]
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        result = await fm_payload_builder_node(state)
        payload_inner = result["backend_refs"]["fm_payload"]["payload"]
        assert payload_inner["expected_handover_date"] == "2026-06-25"

    @pytest.mark.asyncio
    async def test_approve_payload_has_approved_status(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["fm_action"] = "approve"
        state["backend_refs"]["uploaded_documents"] = ["fm-doc-checklist"]
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        result = await fm_payload_builder_node(state)
        assert result["backend_refs"]["fm_payload"]["status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_save_progress_payload_has_in_process_status(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["fm_action"] = "save_progress"
        state["backend_refs"]["uploaded_documents"] = ["fm-doc-checklist"]
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        result = await fm_payload_builder_node(state)
        assert result["backend_refs"]["fm_payload"]["status"] == "IN_PROCESS"


# ---------------------------------------------------------------------------
# fm_api_submission_node — PATCH with documents
# ---------------------------------------------------------------------------


class TestFMApiSubmissionWithDocuments:
    @pytest.mark.asyncio
    async def test_approve_succeeds_sets_fm_approved(self) -> None:
        state = _base_fm_state()
        state["backend_refs"]["fm_action"] = "approve"
        state["backend_refs"]["uploaded_documents"] = [
            "fm-doc-checklist", "fm-doc-survey", "fm-doc-cop"
        ]
        state["backend_refs"]["fm_payload"] = {"status": "APPROVED"}
        state["collected_data"]["expected_handover_date"] = "2026-06-25"

        with patch(
            "app.agents.graph.nodes.handover.fm_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_success())
            ),
        ):
            result = await fm_api_submission_node(state)

        assert result["status"] == "SUBMITTED"
        assert result["backend_refs"]["fm_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_wrong_role_permission_denied(self) -> None:
        state = _base_fm_state(auth=_mall_manager_auth())
        state["backend_refs"]["fm_payload"] = {"status": "APPROVED"}
        state["backend_refs"]["fm_action"] = "approve"

        with patch(
            "app.agents.graph.nodes.handover.fm_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(),
        ):
            result = await fm_api_submission_node(state)

        assert result["status"] == "FAILED"
        assert "permission" in result["response_message"].lower()


# ---------------------------------------------------------------------------
# Full chained FM pipeline
# ---------------------------------------------------------------------------


class TestFMFullChainedPipeline:
    @pytest.mark.asyncio
    async def test_doc_upload_then_merge_then_payload_then_submission(self) -> None:
        """Full FM path: doc upload → merge (auto-calc) → payload → PATCH → approved."""
        state = _base_fm_state()

        # 1. Document upload bridge
        doc_result = await document_upload_node(state)
        state["backend_refs"].update(doc_result["backend_refs"])

        assert "fm-doc-checklist" in state["backend_refs"]["uploaded_documents"]
        assert len(state["backend_refs"]["uploaded_documents"]) == 3

        # 2. Merge state with auto-calc
        merge_result = await merge_state_node(state)
        state["collected_data"].update(merge_result["collected_data"])

        assert state["collected_data"]["expected_handover_date"] == "2026-06-25"

        # 3. Build FM payload (approve path)
        state["backend_refs"]["fm_action"] = "approve"
        pb_result = await fm_payload_builder_node(state)
        state["backend_refs"].update(pb_result["backend_refs"])

        payload = state["backend_refs"]["fm_payload"]
        assert payload["status"] == "APPROVED"
        inner = payload["payload"]
        assert inner["expected_handover_date"] == "2026-06-25"
        assert "fm-doc-checklist" in inner["documents_ids"]

        # 4. Submit to platform
        with patch(
            "app.agents.graph.nodes.handover.fm_api_submission_node.get_service_request_api_service",
            return_value=AsyncMock(
                patch_service_request=AsyncMock(return_value=_mock_patch_success())
            ),
        ):
            sub_result = await fm_api_submission_node(state)

        assert sub_result["status"] == "SUBMITTED"
        assert sub_result["backend_refs"]["fm_status"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_fm_entry_node_proactive_routing(self) -> None:
        """FM Manager with approve action → fm_action set; no WAITING_FOR_USER."""
        state = _base_fm_state(
            action_override="approve_fm_review",
            backend_refs={
                "sr_id": "sr-fm-001",
                "user_role": "FM_MANAGER",
            },
        )
        result = await fm_review_entry_node(state)
        assert result.get("status") != "WAITING_FOR_USER"
        assert result["backend_refs"]["fm_action"] == "approve"
