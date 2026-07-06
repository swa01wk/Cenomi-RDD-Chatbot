"""Unit tests — validate_document_count and ValidationService document-count integration.

Test groups
-----------
TestValidateDocumentCountFMReview   — FM_REVIEW: ≥1 document required before save/approve.
TestValidateDocumentCountRDDReview  — RDD_REVIEW: DR_SR_HANDOVER_REPORT required.
TestValidateDocumentCountOtherStages — Other stages: no count requirement.
TestValidationServiceDocumentCount  — validate_draft() integration with document count.
TestNewDocumentTypes                — SR_HANDOVER_OTHER and SR_REJECTED_HANDOVER_REPORT
                                      are now in ALL_DOCUMENT_TYPES and stage allowlists.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.services.validation_service import (
    ValidationService,
    validate_document_count,
    validate_document_type,
)
from app.agents.schemas.handover_schema import (
    ALL_DOCUMENT_TYPES,
    FM_ALLOWED_DOCUMENTS,
    RDD_ALLOWED_DOCUMENTS,
    RDD_REQUIRED_DOCUMENTS,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _doc(doc_type: str) -> dict[str, Any]:
    return {"document_type": doc_type, "document_id": f"uuid-{doc_type}"}


def _failed(results: list[dict]) -> list[dict]:
    return [r for r in results if r["status"] == "FAILED"]


def _passed(results: list[dict]) -> list[dict]:
    return [r for r in results if r["status"] == "PASSED"]


# ===========================================================================
# TestValidateDocumentCountFMReview
# ===========================================================================


class TestValidateDocumentCountFMReview:
    """FM_REVIEW requires at least one document to be uploaded."""

    def test_no_documents_returns_failure(self) -> None:
        results = validate_document_count([], "FM_REVIEW")
        assert len(_failed(results)) == 1

    def test_empty_list_failure_is_blocking(self) -> None:
        results = validate_document_count([], "FM_REVIEW")
        failed = _failed(results)
        assert failed[0]["blocking"] is True

    def test_empty_list_failure_field_is_documents(self) -> None:
        results = validate_document_count([], "FM_REVIEW")
        assert _failed(results)[0]["field"] == "_documents"

    def test_empty_list_failure_type_is_document_count(self) -> None:
        results = validate_document_count([], "FM_REVIEW")
        assert _failed(results)[0]["validation_type"] == "document_count"

    def test_one_checklist_document_passes(self) -> None:
        results = validate_document_count([_doc("SR_HANDOVER_CHECKLIST")], "FM_REVIEW")
        assert len(_failed(results)) == 0

    def test_one_site_survey_passes(self) -> None:
        results = validate_document_count([_doc("SR_HANDOVER_SITE_SURVEY")], "FM_REVIEW")
        assert len(_failed(results)) == 0

    def test_one_cop_checklist_passes(self) -> None:
        results = validate_document_count([_doc("SR_COP_CHECKLIST_OTHER")], "FM_REVIEW")
        assert len(_failed(results)) == 0

    def test_sr_handover_other_single_doc_passes(self) -> None:
        """SR_HANDOVER_OTHER is now an allowed FM document type."""
        results = validate_document_count([_doc("SR_HANDOVER_OTHER")], "FM_REVIEW")
        assert len(_failed(results)) == 0

    def test_three_fm_documents_passes(self) -> None:
        docs = [
            _doc("SR_HANDOVER_CHECKLIST"),
            _doc("SR_HANDOVER_SITE_SURVEY"),
            _doc("SR_COP_CHECKLIST_OTHER"),
        ]
        results = validate_document_count(docs, "FM_REVIEW")
        assert len(_failed(results)) == 0

    def test_none_documents_treated_as_empty(self) -> None:
        results = validate_document_count(None, "FM_REVIEW")  # type: ignore[arg-type]
        assert len(_failed(results)) == 1

    def test_failure_message_mentions_upload(self) -> None:
        results = validate_document_count([], "FM_REVIEW")
        msg = _failed(results)[0]["message"].lower()
        assert "upload" in msg or "document" in msg


# ===========================================================================
# TestValidateDocumentCountRDDReview
# ===========================================================================


class TestValidateDocumentCountRDDReview:
    """RDD_REVIEW requires DR_SR_HANDOVER_REPORT to be present."""

    def test_no_documents_returns_failure(self) -> None:
        results = validate_document_count([], "RDD_REVIEW")
        assert len(_failed(results)) == 1

    def test_failure_is_blocking(self) -> None:
        results = validate_document_count([], "RDD_REVIEW")
        assert _failed(results)[0]["blocking"] is True

    def test_missing_report_with_other_docs_still_fails(self) -> None:
        """Having FM docs in the RDD stage does not satisfy the RDD report requirement."""
        docs = [_doc("SR_HANDOVER_CHECKLIST"), _doc("SR_HANDOVER_SITE_SURVEY")]
        results = validate_document_count(docs, "RDD_REVIEW")
        assert len(_failed(results)) == 1

    def test_dr_sr_handover_report_passes(self) -> None:
        results = validate_document_count([_doc("DR_SR_HANDOVER_REPORT")], "RDD_REVIEW")
        assert len(_failed(results)) == 0

    def test_report_plus_rejected_report_passes(self) -> None:
        """DR_SR_HANDOVER_REPORT + SR_REJECTED_HANDOVER_REPORT is valid."""
        docs = [_doc("DR_SR_HANDOVER_REPORT"), _doc("SR_REJECTED_HANDOVER_REPORT")]
        results = validate_document_count(docs, "RDD_REVIEW")
        assert len(_failed(results)) == 0

    def test_report_plus_other_passes(self) -> None:
        docs = [_doc("DR_SR_HANDOVER_REPORT"), _doc("SR_HANDOVER_OTHER")]
        results = validate_document_count(docs, "RDD_REVIEW")
        assert len(_failed(results)) == 0

    def test_failure_message_mentions_handover_report(self) -> None:
        results = validate_document_count([], "RDD_REVIEW")
        msg = _failed(results)[0]["message"]
        assert "DR_SR_HANDOVER_REPORT" in msg or "Handover Report" in msg

    def test_document_id_key_alternative(self) -> None:
        """Handles documents where doc type is under 'document_type_id' key."""
        docs = [{"document_type_id": "DR_SR_HANDOVER_REPORT", "document_id": "uuid-1"}]
        results = validate_document_count(docs, "RDD_REVIEW")
        assert len(_failed(results)) == 0


# ===========================================================================
# TestValidateDocumentCountOtherStages
# ===========================================================================


class TestValidateDocumentCountOtherStages:
    """No document count requirement for CREATE_SR or unknown stages."""

    def test_create_sr_no_documents_returns_no_failure(self) -> None:
        results = validate_document_count([], "CREATE_SR")
        assert len(_failed(results)) == 0

    def test_create_sr_returns_empty_list(self) -> None:
        results = validate_document_count([], "CREATE_SR")
        assert results == []

    def test_unknown_stage_returns_empty_list(self) -> None:
        results = validate_document_count([], "UNKNOWN_STAGE")
        assert results == []

    def test_sr_created_no_requirement(self) -> None:
        results = validate_document_count([], "SR_CREATED")
        assert results == []


# ===========================================================================
# TestNewDocumentTypes
# ===========================================================================


class TestNewDocumentTypes:
    """Verify the new document types are correctly registered in the schema."""

    def test_sr_handover_other_in_all_document_types(self) -> None:
        assert "SR_HANDOVER_OTHER" in ALL_DOCUMENT_TYPES

    def test_sr_rejected_handover_report_in_all_document_types(self) -> None:
        assert "SR_REJECTED_HANDOVER_REPORT" in ALL_DOCUMENT_TYPES

    def test_sr_handover_other_in_fm_allowed(self) -> None:
        assert "SR_HANDOVER_OTHER" in FM_ALLOWED_DOCUMENTS

    def test_sr_rejected_handover_report_in_rdd_allowed(self) -> None:
        assert "SR_REJECTED_HANDOVER_REPORT" in RDD_ALLOWED_DOCUMENTS

    def test_sr_handover_other_in_rdd_allowed(self) -> None:
        assert "SR_HANDOVER_OTHER" in RDD_ALLOWED_DOCUMENTS

    def test_dr_sr_handover_report_still_required(self) -> None:
        assert "DR_SR_HANDOVER_REPORT" in RDD_REQUIRED_DOCUMENTS

    def test_sr_rejected_not_in_rdd_required(self) -> None:
        """SR_REJECTED_HANDOVER_REPORT is optional at RDD stage — not required."""
        assert "SR_REJECTED_HANDOVER_REPORT" not in RDD_REQUIRED_DOCUMENTS

    def test_sr_handover_other_valid_for_fm_stage(self) -> None:
        result = validate_document_type("SR_HANDOVER_OTHER", "FM_REVIEW")
        assert result["status"] == "PASSED"

    def test_sr_handover_other_valid_for_rdd_stage(self) -> None:
        result = validate_document_type("SR_HANDOVER_OTHER", "RDD_REVIEW")
        assert result["status"] == "PASSED"

    def test_sr_rejected_handover_report_valid_for_rdd_stage(self) -> None:
        result = validate_document_type("SR_REJECTED_HANDOVER_REPORT", "RDD_REVIEW")
        assert result["status"] == "PASSED"

    def test_sr_rejected_handover_report_invalid_for_fm_stage(self) -> None:
        """Rejected handover report is not an FM document type."""
        result = validate_document_type("SR_REJECTED_HANDOVER_REPORT", "FM_REVIEW")
        assert result["status"] == "FAILED"

    def test_dr_sr_handover_report_invalid_for_fm_stage(self) -> None:
        """The RDD report doc type must not be uploadable during FM review."""
        result = validate_document_type("DR_SR_HANDOVER_REPORT", "FM_REVIEW")
        assert result["status"] == "FAILED"

    def test_fm_checklist_invalid_for_rdd_stage(self) -> None:
        """Handover checklist is an FM doc type — not valid for RDD review."""
        result = validate_document_type("SR_HANDOVER_CHECKLIST", "RDD_REVIEW")
        assert result["status"] == "FAILED"


# ===========================================================================
# TestValidationServiceDocumentCount
# ===========================================================================


class TestValidationServiceDocumentCount:
    """Integration: validate_draft() enforces document count rules."""

    # ── FM_REVIEW — no documents → blocked ─────────────────────────────────

    def test_fm_review_no_docs_produces_blocking_error(self) -> None:
        svc = ValidationService()
        data = {"unit_readiness_date": "2026-07-10", "expected_handover_date": "2026-07-17"}
        errors = svc.validate_draft(data, workflow_stage="FM_REVIEW", documents=[])
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 1
        assert count_errors[0]["blocking"] is True

    def test_fm_review_one_doc_no_count_error(self) -> None:
        svc = ValidationService()
        data = {"unit_readiness_date": "2026-07-10", "expected_handover_date": "2026-07-17"}
        docs = [{"document_type": "SR_HANDOVER_CHECKLIST"}]
        errors = svc.validate_draft(data, workflow_stage="FM_REVIEW", documents=docs)
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 0

    def test_fm_review_sr_handover_other_satisfies_count(self) -> None:
        svc = ValidationService()
        data = {"unit_readiness_date": "2026-07-10", "expected_handover_date": "2026-07-17"}
        docs = [{"document_type": "SR_HANDOVER_OTHER"}]
        errors = svc.validate_draft(data, workflow_stage="FM_REVIEW", documents=docs)
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 0

    # ── RDD_REVIEW — no report → blocked ───────────────────────────────────

    def test_rdd_review_no_report_produces_blocking_error(self) -> None:
        svc = ValidationService()
        data = {
            "guideLineLink": "https://cenomi.com/gl",
            "actual_handover_date": "2026-07-15",
            "fitout_start_date": "2026-07-16",
            "fitout_end_date": "2026-07-20",
            "trading_date": "2026-07-28",
        }
        errors = svc.validate_draft(data, workflow_stage="RDD_REVIEW", documents=[])
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 1
        assert count_errors[0]["blocking"] is True

    def test_rdd_review_with_report_no_count_error(self) -> None:
        svc = ValidationService()
        data = {
            "guideLineLink": "https://cenomi.com/gl",
            "actual_handover_date": "2026-07-15",
            "fitout_start_date": "2026-07-16",
            "fitout_end_date": "2026-07-20",
            "trading_date": "2026-07-28",
        }
        docs = [{"document_type": "DR_SR_HANDOVER_REPORT"}]
        errors = svc.validate_draft(data, workflow_stage="RDD_REVIEW", documents=docs)
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 0

    def test_rdd_review_without_report_fm_docs_not_sufficient(self) -> None:
        """FM checklist does not satisfy the RDD report requirement."""
        svc = ValidationService()
        data = {
            "guideLineLink": "https://cenomi.com/gl",
            "actual_handover_date": "2026-07-15",
            "fitout_start_date": "2026-07-16",
            "fitout_end_date": "2026-07-20",
            "trading_date": "2026-07-28",
        }
        docs = [{"document_type": "SR_HANDOVER_CHECKLIST"}]
        # SR_HANDOVER_CHECKLIST is invalid for RDD stage — 2 errors: count + type
        errors = svc.validate_draft(data, workflow_stage="RDD_REVIEW", documents=docs)
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 1

    # ── CREATE_SR — no document count requirement ───────────────────────────

    def test_create_sr_no_documents_no_count_error(self) -> None:
        svc = ValidationService()
        data: dict[str, Any] = {}
        errors = svc.validate_draft(data, workflow_stage="CREATE_SR", documents=[])
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 0

    # ── None documents default behaviour ───────────────────────────────────

    def test_fm_review_none_documents_triggers_count_error(self) -> None:
        svc = ValidationService()
        data = {"unit_readiness_date": "2026-07-10", "expected_handover_date": "2026-07-17"}
        errors = svc.validate_draft(data, workflow_stage="FM_REVIEW", documents=None)
        count_errors = [e for e in errors if e["validation_type"] == "document_count"]
        assert len(count_errors) == 1
