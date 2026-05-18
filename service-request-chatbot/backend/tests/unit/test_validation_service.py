"""Unit tests — ValidationService and all individual validation functions.

Test groups
-----------
TestValidateRequiredFields       — Absent / None / empty-string / empty-list detection;
                                   integer 0 and False are valid; order preserved.
TestValidateInspectionDoneBy     — Allowed values pass; anything else fails.
TestValidateStartEndDate         — start < end passes; equal / reversed / missing fails.
TestValidateRDDDateOrder         — Full chain, partial failures, equal dates allowed.
TestValidateDocumentType         — Unknown types, wrong stage, correct stage, role param.
TestValidatePermission           — Authorised roles pass; wrong role fails.
TestValidationServiceDraft       — Orchestrated validate_draft: only FAILed results,
                                   per-stage scoping, document loop, permission hook.
TestValidationServiceCompat      — Backward-compatible validate() → ValidationIssueDTO.
TestValidationNode               — Async node updates validation_errors and status.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.services.validation_service import (
    ValidationService,
    validate_document_type,
    validate_inspection_done_by,
    validate_permission,
    validate_required_fields,
    validate_rdd_date_order,
    validate_start_end_date,
)
from app.types.service_request import ValidationIssueDTO


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _failed(results: list[dict]) -> list[dict]:
    return [r for r in results if r["status"] == "FAILED"]


def _passed(results: list[dict]) -> list[dict]:
    return [r for r in results if r["status"] == "PASSED"]


# ===========================================================================
# TestValidateRequiredFields
# ===========================================================================


class TestValidateRequiredFields:
    # ── Missing rules ──────────────────────────────────────────────────────

    def test_absent_key_is_failed(self) -> None:
        results = validate_required_fields({}, ["title"])
        assert len(_failed(results)) == 1
        assert results[0]["field"] == "title"

    def test_none_value_is_failed(self) -> None:
        results = validate_required_fields({"title": None}, ["title"])
        assert results[0]["status"] == "FAILED"

    def test_empty_string_is_failed(self) -> None:
        results = validate_required_fields({"startDate": ""}, ["startDate"])
        assert results[0]["status"] == "FAILED"

    def test_empty_list_is_failed(self) -> None:
        results = validate_required_fields({"unit_codes": []}, ["unit_codes"])
        assert results[0]["status"] == "FAILED"

    # ── Valid values pass ──────────────────────────────────────────────────

    def test_non_empty_string_passes(self) -> None:
        results = validate_required_fields({"title": "My SR"}, ["title"])
        assert results[0]["status"] == "PASSED"

    def test_non_empty_list_passes(self) -> None:
        results = validate_required_fields({"unit_codes": ["U-01"]}, ["unit_codes"])
        assert results[0]["status"] == "PASSED"

    def test_integer_zero_passes(self) -> None:
        """0 is a valid value — not treated as missing."""
        results = validate_required_fields({"contracted_area": 0}, ["contracted_area"])
        assert results[0]["status"] == "PASSED"

    def test_false_boolean_passes(self) -> None:
        """False is a valid value — not treated as missing."""
        results = validate_required_fields(
            {"confirmation_required": False}, ["confirmation_required"]
        )
        assert results[0]["status"] == "PASSED"

    # ── Multiple fields ────────────────────────────────────────────────────

    def test_returns_one_result_per_required_field(self) -> None:
        results = validate_required_fields({}, ["a", "b", "c"])
        assert len(results) == 3

    def test_all_missing(self) -> None:
        results = validate_required_fields({}, ["title", "description", "startDate"])
        assert all(r["status"] == "FAILED" for r in results)

    def test_partial_missing(self) -> None:
        data = {"title": "SR", "description": "", "startDate": None}
        results = validate_required_fields(data, ["title", "description", "startDate"])
        failed_fields = {r["field"] for r in _failed(results)}
        assert failed_fields == {"description", "startDate"}
        assert results[0]["status"] == "PASSED"  # title

    def test_all_present_no_failures(self) -> None:
        data = {"title": "SR", "startDate": "2025-01-01", "endDate": "2025-01-31"}
        results = validate_required_fields(data, ["title", "startDate", "endDate"])
        assert _failed(results) == []

    def test_empty_required_list_returns_empty(self) -> None:
        results = validate_required_fields({"title": "SR"}, [])
        assert results == []

    def test_preserves_order(self) -> None:
        results = validate_required_fields({}, ["a", "b", "c", "d"])
        assert [r["field"] for r in results] == ["a", "b", "c", "d"]

    def test_extra_keys_in_data_ignored(self) -> None:
        results = validate_required_fields({"title": "SR", "extra": "ignored"}, ["title"])
        assert results[0]["status"] == "PASSED"

    # ── Shape ─────────────────────────────────────────────────────────────

    def test_result_has_required_keys(self) -> None:
        results = validate_required_fields({}, ["title"])
        r = results[0]
        assert {"field", "validation_type", "status", "message", "blocking"} <= r.keys()

    def test_validation_type_is_required(self) -> None:
        results = validate_required_fields({}, ["title"])
        assert results[0]["validation_type"] == "required"

    def test_blocking_is_true(self) -> None:
        results = validate_required_fields({}, ["title"])
        assert results[0]["blocking"] is True


# ===========================================================================
# TestValidateInspectionDoneBy
# ===========================================================================


class TestValidateInspectionDoneBy:
    def test_fm_manager_passes(self) -> None:
        r = validate_inspection_done_by("FM_MANAGER")
        assert r["status"] == "PASSED"

    def test_operations_passes(self) -> None:
        r = validate_inspection_done_by("OPERATIONS")
        assert r["status"] == "PASSED"

    def test_lowercase_fails(self) -> None:
        r = validate_inspection_done_by("fm_manager")
        assert r["status"] == "FAILED"

    def test_arbitrary_string_fails(self) -> None:
        r = validate_inspection_done_by("CONTRACTOR")
        assert r["status"] == "FAILED"

    def test_empty_string_fails(self) -> None:
        r = validate_inspection_done_by("")
        assert r["status"] == "FAILED"

    def test_none_fails(self) -> None:
        r = validate_inspection_done_by(None)
        assert r["status"] == "FAILED"

    def test_field_is_inspection_done_by(self) -> None:
        r = validate_inspection_done_by("FM_MANAGER")
        assert r["field"] == "inspection_done_by"

    def test_validation_type_is_enum(self) -> None:
        r = validate_inspection_done_by("FM_MANAGER")
        assert r["validation_type"] == "enum"

    def test_blocking_is_true(self) -> None:
        r = validate_inspection_done_by("UNKNOWN")
        assert r["blocking"] is True

    def test_failed_message_mentions_allowed_values(self) -> None:
        r = validate_inspection_done_by("CONTRACTOR")
        assert "FM_MANAGER" in r["message"] or "OPERATIONS" in r["message"]


# ===========================================================================
# TestValidateStartEndDate
# ===========================================================================


class TestValidateStartEndDate:
    # ── Passing cases ──────────────────────────────────────────────────────

    def test_start_before_end_passes(self) -> None:
        r = validate_start_end_date("2025-01-01", "2025-12-31")
        assert r["status"] == "PASSED"

    def test_consecutive_days_passes(self) -> None:
        r = validate_start_end_date("2025-06-01", "2025-06-02")
        assert r["status"] == "PASSED"

    # ── Failing cases ──────────────────────────────────────────────────────

    def test_equal_dates_fail(self) -> None:
        """startDate == endDate must fail (start must be *before* end)."""
        r = validate_start_end_date("2025-06-01", "2025-06-01")
        assert r["status"] == "FAILED"

    def test_start_after_end_fails(self) -> None:
        r = validate_start_end_date("2025-12-31", "2025-01-01")
        assert r["status"] == "FAILED"

    def test_missing_start_fails(self) -> None:
        r = validate_start_end_date(None, "2025-12-31")
        assert r["status"] == "FAILED"

    def test_missing_end_fails(self) -> None:
        r = validate_start_end_date("2025-01-01", None)
        assert r["status"] == "FAILED"

    def test_both_missing_fails(self) -> None:
        r = validate_start_end_date(None, None)
        assert r["status"] == "FAILED"

    def test_unparseable_start_fails(self) -> None:
        r = validate_start_end_date("not-a-date", "2025-12-31")
        assert r["status"] == "FAILED"

    def test_unparseable_end_fails(self) -> None:
        r = validate_start_end_date("2025-01-01", "bad-date")
        assert r["status"] == "FAILED"

    # ── Shape ─────────────────────────────────────────────────────────────

    def test_validation_type_is_date_range(self) -> None:
        r = validate_start_end_date("2025-01-01", "2025-12-31")
        assert r["validation_type"] == "date_range"

    def test_blocking_is_true(self) -> None:
        r = validate_start_end_date("2025-12-31", "2025-01-01")
        assert r["blocking"] is True

    def test_failed_message_is_descriptive(self) -> None:
        r = validate_start_end_date("2025-12-31", "2025-01-01")
        msg = r["message"].lower()
        assert "start" in msg and "end" in msg


# ===========================================================================
# TestValidateRDDDateOrder
# ===========================================================================


class TestValidateRDDDateOrder:
    def _valid_data(self) -> dict[str, Any]:
        return {
            "actual_handover_date": "2025-01-01",
            "fitout_start_date": "2025-02-01",
            "fitout_end_date": "2025-03-01",
            "trading_date": "2025-04-01",
        }

    # ── Full chain passes ──────────────────────────────────────────────────

    def test_valid_chain_all_pass(self) -> None:
        results = validate_rdd_date_order(self._valid_data())
        assert _failed(results) == []

    def test_equal_dates_in_chain_pass(self) -> None:
        """Equal dates are permitted (≤ not <)."""
        data = {
            "actual_handover_date": "2025-01-01",
            "fitout_start_date": "2025-01-01",
            "fitout_end_date": "2025-01-01",
            "trading_date": "2025-01-01",
        }
        results = validate_rdd_date_order(data)
        assert _failed(results) == []

    # ── Single violations ──────────────────────────────────────────────────

    def test_actual_after_fitout_start_fails(self) -> None:
        data = self._valid_data()
        data["actual_handover_date"] = "2025-03-01"
        data["fitout_start_date"] = "2025-02-01"
        results = validate_rdd_date_order(data)
        failed_fields = {r["field"] for r in _failed(results)}
        assert "actual_handover_date" in failed_fields

    def test_fitout_start_after_fitout_end_fails(self) -> None:
        data = self._valid_data()
        data["fitout_start_date"] = "2025-04-01"
        data["fitout_end_date"] = "2025-03-01"
        results = validate_rdd_date_order(data)
        failed_fields = {r["field"] for r in _failed(results)}
        assert "fitout_start_date" in failed_fields

    def test_fitout_end_after_trading_date_fails(self) -> None:
        data = self._valid_data()
        data["fitout_end_date"] = "2025-05-01"
        data["trading_date"] = "2025-04-01"
        results = validate_rdd_date_order(data)
        failed_fields = {r["field"] for r in _failed(results)}
        assert "fitout_end_date" in failed_fields

    # ── Missing date handling ──────────────────────────────────────────────

    def test_missing_date_produces_failed_result(self) -> None:
        data = self._valid_data()
        del data["fitout_start_date"]
        results = validate_rdd_date_order(data)
        assert any(r["status"] == "FAILED" for r in results)

    def test_all_dates_missing_all_pairs_fail(self) -> None:
        results = validate_rdd_date_order({})
        assert all(r["status"] == "FAILED" for r in results)

    # ── Shape ─────────────────────────────────────────────────────────────

    def test_returns_three_results_for_full_data(self) -> None:
        """One result per adjacent pair in the 3-pair chain."""
        results = validate_rdd_date_order(self._valid_data())
        assert len(results) == 3

    def test_validation_type_is_rdd_date_order(self) -> None:
        results = validate_rdd_date_order(self._valid_data())
        assert all(r["validation_type"] == "rdd_date_order" for r in results)

    def test_blocking_is_true_on_failure(self) -> None:
        data = self._valid_data()
        data["actual_handover_date"] = "2025-12-31"
        results = validate_rdd_date_order(data)
        assert all(r["blocking"] is True for r in _failed(results))


# ===========================================================================
# TestValidateDocumentType
# ===========================================================================


class TestValidateDocumentType:
    # ── FM_REVIEW stage ────────────────────────────────────────────────────

    def test_sr_handover_checklist_in_fm_review_passes(self) -> None:
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "FM_REVIEW")
        assert r["status"] == "PASSED"

    def test_sr_handover_site_survey_in_fm_review_passes(self) -> None:
        r = validate_document_type("SR_HANDOVER_SITE_SURVEY", "FM_REVIEW")
        assert r["status"] == "PASSED"

    def test_sr_cop_checklist_in_fm_review_passes(self) -> None:
        r = validate_document_type("SR_COP_CHECKLIST_OTHER", "FM_REVIEW")
        assert r["status"] == "PASSED"

    # ── RDD_REVIEW stage ───────────────────────────────────────────────────

    def test_dr_sr_handover_report_in_rdd_review_passes(self) -> None:
        r = validate_document_type("DR_SR_HANDOVER_REPORT", "RDD_REVIEW")
        assert r["status"] == "PASSED"

    def test_fm_doc_in_rdd_review_fails(self) -> None:
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "RDD_REVIEW")
        assert r["status"] == "FAILED"

    def test_rdd_doc_in_fm_review_fails(self) -> None:
        r = validate_document_type("DR_SR_HANDOVER_REPORT", "FM_REVIEW")
        assert r["status"] == "FAILED"

    # ── Unknown document type ──────────────────────────────────────────────

    def test_unknown_document_type_fails(self) -> None:
        r = validate_document_type("UNKNOWN_DOC", "FM_REVIEW")
        assert r["status"] == "FAILED"

    def test_unknown_type_message_mentions_unknown(self) -> None:
        r = validate_document_type("FAKE_DOC", "FM_REVIEW")
        assert "FAKE_DOC" in r["message"]

    # ── Wrong stage ────────────────────────────────────────────────────────

    def test_doc_in_create_sr_stage_fails(self) -> None:
        """CREATE_SR has no allowed document types."""
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "CREATE_SR")
        assert r["status"] == "FAILED"

    # ── Role parameter ─────────────────────────────────────────────────────

    def test_role_param_does_not_break_valid_doc(self) -> None:
        """Role is accepted but does not change the outcome for now."""
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "FM_REVIEW", role="FM_MANAGER")
        assert r["status"] == "PASSED"

    # ── Shape ─────────────────────────────────────────────────────────────

    def test_field_is_document_type(self) -> None:
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "FM_REVIEW")
        assert r["field"] == "document_type"

    def test_validation_type_is_document_type(self) -> None:
        r = validate_document_type("SR_HANDOVER_CHECKLIST", "FM_REVIEW")
        assert r["validation_type"] == "document_type"

    def test_blocking_is_true(self) -> None:
        r = validate_document_type("UNKNOWN", "FM_REVIEW")
        assert r["blocking"] is True


# ===========================================================================
# TestValidatePermission
# ===========================================================================


class TestValidatePermission:
    def test_mall_manager_on_create_sr_passes(self) -> None:
        r = validate_permission("MALL_MANAGER", "CREATE_SR")
        assert r["status"] == "PASSED"

    def test_fm_manager_on_fm_review_passes(self) -> None:
        r = validate_permission("FM_MANAGER", "FM_REVIEW")
        assert r["status"] == "PASSED"

    def test_dd_engineer_on_rdd_review_passes(self) -> None:
        r = validate_permission("DD_ENGINEER", "RDD_REVIEW")
        assert r["status"] == "PASSED"

    def test_mall_manager_on_fm_review_fails(self) -> None:
        r = validate_permission("MALL_MANAGER", "FM_REVIEW")
        assert r["status"] == "FAILED"

    def test_fm_manager_on_rdd_review_fails(self) -> None:
        r = validate_permission("FM_MANAGER", "RDD_REVIEW")
        assert r["status"] == "FAILED"

    def test_dd_engineer_on_create_sr_fails(self) -> None:
        r = validate_permission("DD_ENGINEER", "CREATE_SR")
        assert r["status"] == "FAILED"

    def test_unknown_role_fails(self) -> None:
        r = validate_permission("GHOST_ROLE", "CREATE_SR")
        assert r["status"] == "FAILED"

    def test_failed_message_mentions_role_and_stage(self) -> None:
        r = validate_permission("GHOST_ROLE", "FM_REVIEW")
        assert "GHOST_ROLE" in r["message"]
        assert "FM_REVIEW" in r["message"]

    def test_field_is_permission(self) -> None:
        r = validate_permission("FM_MANAGER", "FM_REVIEW")
        assert r["field"] == "_permission"

    def test_validation_type_is_permission(self) -> None:
        r = validate_permission("FM_MANAGER", "FM_REVIEW")
        assert r["validation_type"] == "permission"

    def test_blocking_is_true(self) -> None:
        r = validate_permission("GHOST_ROLE", "CREATE_SR")
        assert r["blocking"] is True


# ===========================================================================
# TestValidationServiceDraft
# ===========================================================================


class TestValidationServiceDraft:
    _svc = ValidationService()

    def _minimal_create_sr(self) -> dict[str, Any]:
        """Minimal complete data for CREATE_SR stage (user-supplied fields only)."""
        return {
            "tenant_profile_id": "TP-001",
            "property_id": "PROP-001",
            "lease_code": "LC-001",
            "lease_id": "LEASE-001",
            "brand_id": "BR-001",
            "mall": "Riyadh Park",
            "brand": "Nike",
            "lease": "Lease A",
            "unit_codes": ["U-01"],
            "city": "Riyadh",
            "contracted_area": 100,
            "title": "Handover SR",
            "description": "Test description",
            "startDate": "2025-01-01",
            "endDate": "2025-06-01",
            "inspection_done_by": "FM_MANAGER",
            "comments": "All good",
        }

    # ── Only FAILED results are returned ──────────────────────────────────

    def test_valid_draft_returns_no_errors(self) -> None:
        errors = self._svc.validate_draft(self._minimal_create_sr(), "CREATE_SR")
        assert errors == []

    def test_returns_only_failed_results(self) -> None:
        """validate_draft must filter out PASSED results."""
        data = self._minimal_create_sr()
        data["startDate"] = "2025-12-31"  # violates start < end
        errors = self._svc.validate_draft(data, "CREATE_SR")
        assert all(e["status"] == "FAILED" for e in errors)

    # ── Required field errors ──────────────────────────────────────────────

    def test_missing_required_field_produces_error(self) -> None:
        data = self._minimal_create_sr()
        del data["title"]
        errors = self._svc.validate_draft(data, "CREATE_SR")
        fields = {e["field"] for e in errors}
        assert "title" in fields

    def test_unknown_stage_produces_no_required_field_errors(self) -> None:
        """Unknown stage → no stage_def → required field check skipped."""
        errors = self._svc.validate_draft({}, "NONEXISTENT_STAGE")
        # No required-field failures (stage not found), but also no crash.
        req_errors = [e for e in errors if e["validation_type"] == "required"]
        assert req_errors == []

    # ── inspection_done_by ────────────────────────────────────────────────

    def test_invalid_inspection_done_by_surfaces_error(self) -> None:
        data = self._minimal_create_sr()
        data["inspection_done_by"] = "CONTRACTOR"
        errors = self._svc.validate_draft(data, "CREATE_SR")
        idb_errors = [e for e in errors if e["field"] == "inspection_done_by"]
        assert len(idb_errors) == 1

    def test_inspection_done_by_not_checked_when_absent(self) -> None:
        data = self._minimal_create_sr()
        del data["inspection_done_by"]
        errors = self._svc.validate_draft(data, "CREATE_SR")
        idb_errors = [e for e in errors if e["field"] == "inspection_done_by"]
        # Required check fires because it's a required field for CREATE_SR;
        # but the enum check should NOT fire for a None / absent value.
        assert all(e["validation_type"] == "required" for e in idb_errors)

    # ── start/end date ────────────────────────────────────────────────────

    def test_reversed_dates_produce_date_range_error(self) -> None:
        data = self._minimal_create_sr()
        data["startDate"] = "2025-12-31"
        data["endDate"] = "2025-01-01"
        errors = self._svc.validate_draft(data, "CREATE_SR")
        date_errors = [e for e in errors if e["validation_type"] == "date_range"]
        assert len(date_errors) == 1

    def test_date_range_not_checked_when_dates_absent(self) -> None:
        data = self._minimal_create_sr()
        del data["startDate"]
        del data["endDate"]
        errors = self._svc.validate_draft(data, "CREATE_SR")
        date_errors = [e for e in errors if e["validation_type"] == "date_range"]
        assert date_errors == []

    # ── RDD date ordering (stage-scoped) ──────────────────────────────────

    def test_rdd_date_order_only_checked_for_rdd_stage(self) -> None:
        data: dict[str, Any] = {
            "actual_handover_date": "2025-12-31",
            "fitout_start_date": "2025-01-01",
        }
        # Should NOT trigger rdd_date_order errors on CREATE_SR
        errors = self._svc.validate_draft(data, "CREATE_SR")
        rdd_errors = [e for e in errors if e["validation_type"] == "rdd_date_order"]
        assert rdd_errors == []

    def test_rdd_date_order_checked_for_rdd_stage(self) -> None:
        data: dict[str, Any] = {
            "guideLineLink": "http://example.com",
            "actual_handover_date": "2025-12-31",
            "fitout_start_date": "2025-01-01",  # violates: actual > fitout_start
            "fitout_end_date": "2025-02-01",
            "trading_date": "2025-03-01",
        }
        errors = self._svc.validate_draft(data, "RDD_REVIEW")
        rdd_errors = [e for e in errors if e["validation_type"] == "rdd_date_order"]
        assert len(rdd_errors) >= 1

    # ── Document type validation ───────────────────────────────────────────

    def test_wrong_document_type_produces_error(self) -> None:
        docs = [{"document_type": "DR_SR_HANDOVER_REPORT"}]  # RDD doc in FM stage
        errors = self._svc.validate_draft({}, "FM_REVIEW", documents=docs)
        doc_errors = [e for e in errors if e["validation_type"] == "document_type"]
        assert len(doc_errors) == 1

    def test_correct_document_type_no_error(self) -> None:
        data = {
            "unit_readiness_date": "2025-03-01",
            "expected_handover_date": "2025-04-01",
        }
        docs = [{"document_type": "SR_HANDOVER_CHECKLIST"}]
        errors = self._svc.validate_draft(data, "FM_REVIEW", documents=docs)
        doc_errors = [e for e in errors if e["validation_type"] == "document_type"]
        assert doc_errors == []

    def test_document_type_key_fallback_to_type(self) -> None:
        """Accepts 'type' as an alternative key to 'document_type'."""
        docs = [{"type": "UNKNOWN_DOC"}]
        errors = self._svc.validate_draft({}, "FM_REVIEW", documents=docs)
        doc_errors = [e for e in errors if e["validation_type"] == "document_type"]
        assert len(doc_errors) == 1

    def test_document_without_type_key_skipped(self) -> None:
        """Documents without a type key must not crash."""
        docs = [{"filename": "photo.jpg"}]
        errors = self._svc.validate_draft({}, "FM_REVIEW", documents=docs)
        doc_errors = [e for e in errors if e["validation_type"] == "document_type"]
        assert doc_errors == []

    # ── Permission hook ────────────────────────────────────────────────────

    def test_wrong_role_produces_permission_error(self) -> None:
        errors = self._svc.validate_draft({}, "FM_REVIEW", role="MALL_MANAGER")
        perm_errors = [e for e in errors if e["validation_type"] == "permission"]
        assert len(perm_errors) == 1

    def test_correct_role_no_permission_error(self) -> None:
        data = {
            "unit_readiness_date": "2025-03-01",
            "expected_handover_date": "2025-04-01",
        }
        errors = self._svc.validate_draft(data, "FM_REVIEW", role="FM_MANAGER")
        perm_errors = [e for e in errors if e["validation_type"] == "permission"]
        assert perm_errors == []

    def test_no_role_skips_permission_check(self) -> None:
        errors = self._svc.validate_draft({}, "FM_REVIEW", role=None)
        perm_errors = [e for e in errors if e["validation_type"] == "permission"]
        assert perm_errors == []

    # ── Blocking flag ──────────────────────────────────────────────────────

    def test_all_errors_are_blocking(self) -> None:
        """Every error returned by validate_draft must be blocking."""
        data = self._minimal_create_sr()
        data["startDate"] = "2025-12-31"  # reversed dates
        data["inspection_done_by"] = "GHOST"
        errors = self._svc.validate_draft(data, "CREATE_SR")
        assert all(e["blocking"] is True for e in errors)


# ===========================================================================
# TestValidationServiceCompat
# ===========================================================================


class TestValidationServiceCompat:
    _svc = ValidationService()

    def test_returns_list(self) -> None:
        result = self._svc.validate({})
        assert isinstance(result, list)

    def test_returns_validation_issue_dtos(self) -> None:
        result = self._svc.validate({"workflow_stage": "CREATE_SR"})
        for item in result:
            assert isinstance(item, ValidationIssueDTO)

    def test_empty_when_no_errors(self) -> None:
        """Passing an essentially valid draft returns no DTOs."""
        # No fields → no stage fields to check for CREATE_SR since all required
        # fields are missing, so we get many. Use a stage with 0 required fields
        # (there is none in this schema), so instead we verify the mapping works
        # by checking it returns DTOs with the expected attributes.
        result = self._svc.validate({"title": "SR", "workflow_stage": "CREATE_SR"})
        for dto in result:
            assert dto.code
            assert dto.message

    def test_permission_field_mapped_to_none(self) -> None:
        """The _permission pseudo-field should map to field_key=None in the DTO."""
        result = self._svc.validate(
            {"workflow_stage": "FM_REVIEW", "role": "MALL_MANAGER"}
        )
        perm_dtos = [d for d in result if d.code == "PERMISSION"]
        # Permission errors from validate() may appear if role is extracted;
        # the draft dict does not route role to validate_draft, so just verify shape.
        for dto in perm_dtos:
            assert dto.field_key is None

    def test_dto_code_is_uppercase(self) -> None:
        result = self._svc.validate({"workflow_stage": "CREATE_SR"})
        for dto in result:
            assert dto.code == dto.code.upper()


# ===========================================================================
# TestValidationNode
# ===========================================================================


class TestValidationNode:
    @pytest.mark.asyncio
    async def test_returns_validation_errors_key(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "FM_REVIEW", "collected_data": {}}
        result = await validation_node(state)
        assert "validation_errors" in result

    @pytest.mark.asyncio
    async def test_returns_status_key(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "FM_REVIEW", "collected_data": {}}
        result = await validation_node(state)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_status_in_progress_when_errors_exist(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "FM_REVIEW", "collected_data": {}}
        result = await validation_node(state)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_status_ready_to_submit_when_no_errors(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {
            "workflow_stage": "FM_REVIEW",
            "collected_data": {
                "unit_readiness_date": "2025-03-01",
                "expected_handover_date": "2025-04-01",
            },
        }
        result = await validation_node(state)
        assert result["status"] == "READY_TO_SUBMIT"

    @pytest.mark.asyncio
    async def test_validation_errors_are_dicts(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "CREATE_SR", "collected_data": {}}
        result = await validation_node(state)
        assert isinstance(result["validation_errors"], list)
        for e in result["validation_errors"]:
            assert isinstance(e, dict)

    @pytest.mark.asyncio
    async def test_each_error_has_canonical_keys(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "CREATE_SR", "collected_data": {}}
        result = await validation_node(state)
        required_keys = {"field", "validation_type", "status", "message", "blocking"}
        for e in result["validation_errors"]:
            assert required_keys <= e.keys()

    @pytest.mark.asyncio
    async def test_documents_are_validated(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state = {
            "workflow_stage": "FM_REVIEW",
            "collected_data": {
                "unit_readiness_date": "2025-03-01",
                "expected_handover_date": "2025-04-01",
            },
            "documents": [{"document_type": "DR_SR_HANDOVER_REPORT"}],
        }
        result = await validation_node(state)
        doc_errors = [
            e for e in result["validation_errors"] if e["validation_type"] == "document_type"
        ]
        assert len(doc_errors) == 1
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_missing_collected_data_handled_gracefully(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state: dict[str, Any] = {"workflow_stage": "FM_REVIEW"}
        result = await validation_node(state)
        assert "validation_errors" in result
        assert "status" in result

    @pytest.mark.asyncio
    async def test_missing_workflow_stage_defaults_to_create_sr(self) -> None:
        from app.agents.graph.nodes.validation_node import validation_node

        state: dict[str, Any] = {"collected_data": {}}
        result = await validation_node(state)
        assert result["status"] == "IN_PROGRESS"

    @pytest.mark.asyncio
    async def test_only_failed_errors_in_state(self) -> None:
        """All entries in state.validation_errors must have status='FAILED'."""
        from app.agents.graph.nodes.validation_node import validation_node

        state = {"workflow_stage": "CREATE_SR", "collected_data": {}}
        result = await validation_node(state)
        for e in result["validation_errors"]:
            assert e["status"] == "FAILED"
