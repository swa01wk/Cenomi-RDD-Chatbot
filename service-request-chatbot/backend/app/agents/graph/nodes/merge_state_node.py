"""Merge partial updates into canonical draft state.

Merge rules
-----------
1. ``extracted_fields`` values are merged into ``collected_data``.
2. Backend-derived protected fields are **never** overwritten by LLM extraction.
3. Low-confidence extractions (below ``_CONFIDENCE_THRESHOLD``) are silently skipped.
4. When an extraction changes a field that was already known, the old value and
   timestamp are appended to ``collected_data["_corrections"]`` so every user
   correction is auditable.
5. ``collected_data`` is the single source of truth for the request draft.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from app.agents.graph.state import ServiceRequestState
from app.observability.decorators import trace_node


def _add_days(date_str: str, days: int) -> str:
    """Add calendar days to a date string, returning YYYY-MM-DD.

    Accepts YYYY-MM-DD, DD/MM/YYYY, and DD-MM-YYYY input formats.
    Returns the input unchanged when it cannot be parsed.
    """
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return (dt + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

# ---------------------------------------------------------------------------
# Backend-derived protected fields
# ---------------------------------------------------------------------------
# These are populated exclusively by backend API lookups (lease resolution,
# tenant profile fetch, etc.).  LLM extraction output must never overwrite them.

BACKEND_PROTECTED_FIELDS: frozenset[str] = frozenset(
    {
        "tenant_profile_id",
        "property_id",
        "brand_id",
        "lease_id",
        "contract_id",
        "unit_codes",
        "city",
        "contracted_area",
        "lease_brand_mall",
    }
)

# Fields that become immutable once the lease has been confirmed via the API
# (i.e. lease_id is present in collected_data).  Before lease resolution the
# user must be free to provide / correct these identifiers; after resolution
# they are backend-authoritative and must not be overwritten by subsequent LLM
# extractions (e.g. the model hallucinating "the current lease code i have
# shared" as a lease_code value).
_LEASE_CONFIRMED_FIELDS: frozenset[str] = frozenset({"lease_code", "mall", "brand"})

# Minimum confidence score required to accept an LLM-extracted value.
_CONFIDENCE_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


_FALLBACK_OPTIONAL_FIELDS: frozenset[str] = frozenset({"comments", "notes"})
"""Optional fields where the bot should directly store the user message when the
LLM under-extracts.  ``description`` is intentionally excluded because it can be
confused with date strings or other fields when extracted out of context."""

_COMMAND_PHRASES: frozenset[str] = frozenset(
    {"cancel", "start over", "restart", "new request", "different request", "begin again", "reset"}
)
"""Structural commands that must NOT be stored as optional-field values."""

# Recognised user-facing phrases for inspection_done_by enum values.
# Used in Fallback C when the LLM under-extracts this field.
_IDB_FM_PHRASES: tuple[str, ...] = ("fm manager", "fm_manager", "fm", "facility manager", "facilitymanager")
_IDB_OPS_PHRASES: tuple[str, ...] = ("operations", "operation", "ops", "operations manager")


@trace_node("merge_state", "CHAIN")
async def merge_state_node(state: ServiceRequestState) -> dict[str, Any]:
    """Merge ``extracted_fields`` and ``corrected_fields`` into ``collected_data``."""
    collected: dict[str, Any] = dict(state.get("collected_data") or {})

    # ── Read last-asked-field hint embedded by missing_field_node ─────────────
    # missing_field_node stores _last_asked_field in collected_data because
    # response_ui is not persisted between turns.  Extract and remove it here
    # so it never leaks into the platform API payload.
    last_asked_field: str | None = collected.pop("_last_asked_field", None) or None
    extracted: dict[str, Any] = state.get("extracted_fields") or {}

    # ── Apply inline edits from the confirmation card first ────────────────
    # corrected_fields come directly from the user's UI interaction, so they
    # are treated as maximum-confidence updates and bypass the normal threshold.
    # Backend-protected fields are still guarded.
    corrected: dict[str, Any] = state.get("corrected_fields") or {}  # type: ignore[assignment]
    for field_name, value in corrected.items():
        if field_name in BACKEND_PROTECTED_FIELDS:
            continue
        if value is not None:
            collected[field_name] = value

    corrections: list[dict[str, Any]] = list(collected.get("_corrections") or [])

    # Once the lease is resolved (lease_id present) the user-facing lease
    # identifiers are considered authoritative and must not be overwritten.
    lease_resolved = bool(collected.get("lease_id"))

    for field_name, extraction in extracted.items():
        # Never overwrite backend-derived fields from LLM extraction.
        if field_name in BACKEND_PROTECTED_FIELDS:
            continue

        # After lease resolution, protect the confirmed identifiers.
        if lease_resolved and field_name in _LEASE_CONFIRMED_FIELDS:
            continue

        # Support both rich extraction shape {value, confidence} and plain values.
        if isinstance(extraction, dict):
            new_value = extraction.get("value")
            confidence = float(extraction.get("confidence", 1.0))
        else:
            new_value = extraction
            confidence = 1.0

        # Skip low-confidence proposals.
        if confidence < _CONFIDENCE_THRESHOLD:
            continue

        # Normalise the "None" sentinel that the extraction prompt emits when
        # the user explicitly declines an optional field (e.g. "no comments").
        # Storing the literal string "None" would cause it to be submitted
        # verbatim to the upstream API; empty string is the correct neutral value.
        if new_value == "None":
            new_value = ""

        # Skip explicitly null proposals.
        if new_value is None:
            continue

        # ── inspection_done_by: normalise and reject garbage values ─────────
        # The LLM may return natural-language variants ("FM Manager",
        # "Operations") or accidentally extract a non-inspector value (e.g. a
        # date string like "2026-09-15").  Canonicalise recognised variants and
        # reject anything unrecognisable so a valid existing value is never
        # overwritten by garbage.
        if field_name == "inspection_done_by":
            idb_lower = str(new_value).strip().lower().replace(" ", "_")
            if idb_lower in (
                "fm_manager", "fm", "fm_review", "facilitymanager", "facility_manager",
            ):
                new_value = "FM_MANAGER"
            elif idb_lower in (
                "operations", "operation", "ops", "operations_manager",
            ):
                new_value = "OPERATIONS"
            elif new_value not in ("FM_MANAGER", "OPERATIONS"):
                # Unknown / garbage extraction — discard to protect existing value.
                continue

        current_value = collected.get(field_name)

        # Record correction when user changes a previously known value.
        if current_value is not None and current_value != new_value:
            corrections.append(
                {
                    "field": field_name,
                    "old_value": current_value,
                    "new_value": new_value,
                    "corrected_at": datetime.datetime.utcnow().isoformat(),
                }
            )

        collected[field_name] = new_value

    if corrections:
        collected["_corrections"] = corrections

    # ── Fallback A: store user message as last-asked optional field ───────────
    # When missing_field_node asked for an optional field (comments / notes) and
    # the LLM extraction did not produce a confident value for it, directly store
    # the user's raw message.  This prevents infinite re-asking loops caused by
    # LLM under-extraction on short or ambiguous optional-field answers.
    user_msg: str = (state.get("user_message") or "").strip()
    if (
        last_asked_field in _FALLBACK_OPTIONAL_FIELDS
        and collected.get(last_asked_field) is None
        and user_msg
        and not any(phrase in user_msg.lower() for phrase in _COMMAND_PHRASES)
    ):
        collected[last_asked_field] = user_msg

    # ── Fallback B: sole remaining optional field + prior turn confirmation ───────
    # A stronger safety net for cases where missing_field_node's _last_asked_field
    # was not set (e.g. the bot's prior path bypassed missing_field_node).
    #
    # Only fires when ALL of:
    #   1. The ONLY remaining missing fields are optional fallback fields (comments/notes)
    #   2. _last_asked_field from the PRIOR turn also points to the same optional field
    #      (or _last_asked_field is not set but we've already confirmed it via Fallback A
    #      not firing — meaning the field is still None after Fallback A ran).
    #
    # The key guard: last_asked_field must agree with the optional field, OR
    # last_asked_field is None but no non-optional required fields are missing.
    # This prevents Fallback B from misfiring when the bot asked for a
    # non-optional field (like inspection_done_by) and the user's answer
    # also happens to be the only optional remaining field.
    from app.agents.schemas.handover_schema import (
        get_missing_fields as _schema_missing,
        OPTIONAL_FIELDS as _OPTIONAL_FIELDS,
    )
    _workflow_stage: str = state.get("workflow_stage") or "CREATE_SR"
    _still_missing: list[str] = _schema_missing(_workflow_stage, collected)
    _optional_still_missing: list[str] = [
        f for f in _still_missing if f in _OPTIONAL_FIELDS and f in _FALLBACK_OPTIONAL_FIELDS
    ]
    _last_matches_optional = (
        last_asked_field in _optional_still_missing
        if last_asked_field
        else False
    )
    if (
        _still_missing  # something is missing
        and _still_missing == _optional_still_missing  # ALL missing are optional fallback fields
        and len(_optional_still_missing) == 1  # exactly one such field
        and _last_matches_optional  # prior turn explicitly asked for this optional field
        and user_msg
        and not any(phrase in user_msg.lower() for phrase in _COMMAND_PHRASES)
    ):
        collected[_optional_still_missing[0]] = user_msg

    # ── Fallback C: inspection_done_by when LLM under-extracts ────────────────
    # When the bot explicitly asked for inspection_done_by (last_asked_field) and
    # the LLM returned nothing confident, parse the user message directly using
    # known natural-language variants.  This prevents the bot from looping on
    # inspector collection when the user already said "FM Manager" or "Operations".
    if (
        last_asked_field == "inspection_done_by"
        and collected.get("inspection_done_by") is None
        and user_msg
    ):
        _msg_lower = user_msg.lower()
        if any(phrase in _msg_lower for phrase in _IDB_FM_PHRASES):
            collected["inspection_done_by"] = "FM_MANAGER"
        elif any(phrase in _msg_lower for phrase in _IDB_OPS_PHRASES):
            collected["inspection_done_by"] = "OPERATIONS"

    # ── Auto-generate title when lease_code + description are now available ──
    # Title is system-generated in the format:
    #   handover-{lease_code}-{description_slug}
    # The bot never asks the user for the title; it is derived automatically
    # once both source fields are present.
    #
    # Use `is not None` (not a falsy check) so that an empty-string description
    # — written when the user explicitly says "no description" — still triggers
    # title generation.  A falsy check would leave title unset indefinitely
    # whenever the user declines to provide a description.
    if not collected.get("title") and collected.get("lease_code") and collected.get("description") is not None:
        collected["title"] = _generate_title(
            str(collected["lease_code"]),
            str(collected["description"]),
        )

    # ── FM_REVIEW: auto-calculate expected_handover_date ─────────────────────
    # Business rule: expected_handover_date = unit_readiness_date + 7 calendar days.
    # Never ask the user for this field — it is always computed here.
    stage = state.get("workflow_stage") or ""
    if stage == "FM_REVIEW":
        readiness = collected.get("unit_readiness_date", "")
        if readiness and not collected.get("expected_handover_date"):
            collected["expected_handover_date"] = _add_days(str(readiness), 7)

    return {"collected_data": collected}


def _generate_title(lease_code: str, description: str) -> str:
    """Build 'handover-{lease_code}-{slug}' from lease_code and description.

    The slug is the first five significant words of the description,
    lowercased and joined with hyphens.  Non-alphanumeric characters are
    stripped so the title is URL-safe and consistent.

    When *description* is empty the trailing separator is omitted, producing
    'handover-{lease_code}' rather than 'handover-{lease_code}-'.
    """
    slug_words = re.sub(r"[^a-zA-Z0-9\s]", "", description.lower()).split()
    slug = "-".join(slug_words[:5])
    return f"handover-{lease_code}-{slug}" if slug else f"handover-{lease_code}"
