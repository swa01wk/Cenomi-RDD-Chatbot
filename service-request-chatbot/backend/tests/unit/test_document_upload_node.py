"""Unit tests for document_upload_node.

Coverage
--------
- 3 FM docs → uploaded_documents has all 3 IDs
- 1 RDD report → rdd_document_id set; uploaded_documents empty
- Mixed FM + RDD docs → both partitions correct
- Duplicate FM doc ID → deduplicated
- Pre-existing uploaded_documents → merged, not replaced
- document_id=None → silently skipped
- Empty state["documents"] → safe, uploaded_documents=[], rdd_document_id unset
- Missing state["documents"] key → no KeyError
- Returns only backend_refs — no other state keys mutated
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.graph.nodes.document_upload_node import document_upload_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-upload-001",
        "user_id": "user-001",
        "trace_id": None,
        "trace_manager": None,
        "backend_refs": {},
        "documents": [],
    }
    base.update(kwargs)
    return base


def _fm_doc(doc_id: str, doc_type: str = "SR_HANDOVER_CHECKLIST") -> dict[str, Any]:
    return {"document_id": doc_id, "document_type_id": doc_type}


def _rdd_doc(doc_id: str) -> dict[str, Any]:
    return {"document_id": doc_id, "document_type_id": "DR_SR_HANDOVER_REPORT"}


# ---------------------------------------------------------------------------
# FM document partitioning
# ---------------------------------------------------------------------------


class TestFMDocumentPartitioning:
    @pytest.mark.asyncio
    async def test_three_fm_docs_all_captured(self) -> None:
        docs = [
            _fm_doc("fm-001", "SR_HANDOVER_CHECKLIST"),
            _fm_doc("fm-002", "SR_HANDOVER_SITE_SURVEY"),
            _fm_doc("fm-003", "SR_COP_CHECKLIST_OTHER"),
        ]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert "fm-001" in uploaded
        assert "fm-002" in uploaded
        assert "fm-003" in uploaded
        assert len(uploaded) == 3

    @pytest.mark.asyncio
    async def test_fm_docs_do_not_set_rdd_doc_id(self) -> None:
        docs = [_fm_doc("fm-001")]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        assert "rdd_document_id" not in result["backend_refs"]

    @pytest.mark.asyncio
    async def test_checklist_doc_type_accepted(self) -> None:
        state = _state(documents=[_fm_doc("chk-001", "SR_HANDOVER_CHECKLIST")])
        result = await document_upload_node(state)
        assert "chk-001" in result["backend_refs"]["uploaded_documents"]

    @pytest.mark.asyncio
    async def test_site_survey_doc_type_accepted(self) -> None:
        state = _state(documents=[_fm_doc("srv-001", "SR_HANDOVER_SITE_SURVEY")])
        result = await document_upload_node(state)
        assert "srv-001" in result["backend_refs"]["uploaded_documents"]

    @pytest.mark.asyncio
    async def test_cop_checklist_doc_type_accepted(self) -> None:
        state = _state(documents=[_fm_doc("cop-001", "SR_COP_CHECKLIST_OTHER")])
        result = await document_upload_node(state)
        assert "cop-001" in result["backend_refs"]["uploaded_documents"]


# ---------------------------------------------------------------------------
# RDD document partitioning
# ---------------------------------------------------------------------------


class TestRDDDocumentPartitioning:
    @pytest.mark.asyncio
    async def test_rdd_report_sets_rdd_document_id(self) -> None:
        state = _state(documents=[_rdd_doc("rdd-report-001")])
        result = await document_upload_node(state)
        assert result["backend_refs"]["rdd_document_id"] == "rdd-report-001"

    @pytest.mark.asyncio
    async def test_rdd_report_does_not_populate_fm_list(self) -> None:
        state = _state(documents=[_rdd_doc("rdd-report-001")])
        result = await document_upload_node(state)
        assert result["backend_refs"]["uploaded_documents"] == []

    @pytest.mark.asyncio
    async def test_last_rdd_doc_wins(self) -> None:
        """When two RDD docs are present, last one's ID is stored."""
        docs = [_rdd_doc("rdd-001"), _rdd_doc("rdd-002")]
        state = _state(documents=docs)
        result = await document_upload_node(state)
        assert result["backend_refs"]["rdd_document_id"] == "rdd-002"


# ---------------------------------------------------------------------------
# Mixed FM + RDD
# ---------------------------------------------------------------------------


class TestMixedDocuments:
    @pytest.mark.asyncio
    async def test_mixed_partitioned_correctly(self) -> None:
        docs = [
            _fm_doc("fm-001", "SR_HANDOVER_CHECKLIST"),
            _fm_doc("fm-002", "SR_HANDOVER_SITE_SURVEY"),
            _rdd_doc("rdd-001"),
        ]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        refs = result["backend_refs"]
        assert "fm-001" in refs["uploaded_documents"]
        assert "fm-002" in refs["uploaded_documents"]
        assert refs["rdd_document_id"] == "rdd-001"

    @pytest.mark.asyncio
    async def test_all_three_fm_plus_rdd(self) -> None:
        docs = [
            _fm_doc("c-001", "SR_HANDOVER_CHECKLIST"),
            _fm_doc("s-001", "SR_HANDOVER_SITE_SURVEY"),
            _fm_doc("p-001", "SR_COP_CHECKLIST_OTHER"),
            _rdd_doc("r-001"),
        ]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        refs = result["backend_refs"]
        assert len(refs["uploaded_documents"]) == 3
        assert refs["rdd_document_id"] == "r-001"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_fm_doc_id_deduplicated(self) -> None:
        docs = [
            _fm_doc("fm-dup-001", "SR_HANDOVER_CHECKLIST"),
            _fm_doc("fm-dup-001", "SR_HANDOVER_CHECKLIST"),  # duplicate
            _fm_doc("fm-002", "SR_HANDOVER_SITE_SURVEY"),
        ]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert uploaded.count("fm-dup-001") == 1
        assert len(uploaded) == 2

    @pytest.mark.asyncio
    async def test_pre_existing_fm_ids_merged_not_replaced(self) -> None:
        """IDs already in backend_refs["uploaded_documents"] are preserved."""
        state = _state(
            documents=[_fm_doc("fm-new-001", "SR_HANDOVER_CHECKLIST")],
            backend_refs={"uploaded_documents": ["existing-id-001"]},
        )
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert "existing-id-001" in uploaded
        assert "fm-new-001" in uploaded

    @pytest.mark.asyncio
    async def test_pre_existing_ids_not_duplicated_on_reupload(self) -> None:
        """If the same doc is uploaded again, it should not appear twice."""
        state = _state(
            documents=[_fm_doc("fm-001", "SR_HANDOVER_CHECKLIST")],
            backend_refs={"uploaded_documents": ["fm-001"]},
        )
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert uploaded.count("fm-001") == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_document_id_none_skipped(self) -> None:
        docs = [
            {"document_id": None, "document_type_id": "SR_HANDOVER_CHECKLIST"},
            _fm_doc("fm-valid-001", "SR_HANDOVER_CHECKLIST"),
        ]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        uploaded = result["backend_refs"]["uploaded_documents"]
        assert None not in uploaded
        assert "fm-valid-001" in uploaded

    @pytest.mark.asyncio
    async def test_empty_documents_list_safe(self) -> None:
        state = _state(documents=[])
        result = await document_upload_node(state)

        refs = result["backend_refs"]
        assert refs["uploaded_documents"] == []
        assert "rdd_document_id" not in refs

    @pytest.mark.asyncio
    async def test_missing_documents_key_safe(self) -> None:
        """state without 'documents' key should not raise KeyError."""
        state = {
            "session_id": "sess-001",
            "backend_refs": {},
            "trace_manager": None,
            "trace_id": None,
        }
        result = await document_upload_node(state)
        assert "backend_refs" in result
        assert result["backend_refs"]["uploaded_documents"] == []

    @pytest.mark.asyncio
    async def test_unknown_doc_type_not_partitioned(self) -> None:
        """An unknown document type is neither FM nor RDD — silently ignored."""
        docs = [{"document_id": "unk-001", "document_type_id": "UNKNOWN_TYPE"}]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        refs = result["backend_refs"]
        assert refs["uploaded_documents"] == []
        assert "rdd_document_id" not in refs

    @pytest.mark.asyncio
    async def test_doc_missing_document_type_id_key(self) -> None:
        """A doc dict without document_type_id key falls back to empty string — no crash."""
        docs = [{"document_id": "no-type-001"}]
        state = _state(documents=docs)
        result = await document_upload_node(state)

        assert result["backend_refs"]["uploaded_documents"] == []

    @pytest.mark.asyncio
    async def test_returns_only_backend_refs(self) -> None:
        """The node must return only backend_refs; no other state keys."""
        docs = [_fm_doc("fm-001")]
        state = _state(documents=docs, collected_data={"unit_readiness_date": "2026-06-01"})
        result = await document_upload_node(state)

        assert list(result.keys()) == ["backend_refs"]
