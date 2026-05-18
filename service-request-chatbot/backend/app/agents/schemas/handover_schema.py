"""Handover Service Request — workflow configuration schema.

This module is the single source of truth for:
- Stage definitions (required fields + required documents per stage)
- Role assignments
- Allowed extractable fields
- Backend-derived (non-extractable) fields
- Document type registries
- Role → stage permission map

Graph nodes **must not** hard-code required fields.  Instead they should
query ``STAGE_REGISTRY[state["workflow_stage"]]``.

LLM extraction output shape lives in ``HandoverExtractedFields`` (Pydantic).
``HandoverExtractionSchema`` is kept for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, Field as PydanticField, field_validator, model_validator

# ── Constants ─────────────────────────────────────────────────────────────────

SERVICE_CATEGORY: Final[str] = "FIT_OUT_AND_HANDOVER"
SUB_CATEGORY: Final[str] = "HANDOVER"
ASSIGNMENT_TYPE: Final[str] = "workflow"

# ── Literal types ─────────────────────────────────────────────────────────────

WorkflowStage = Literal["CREATE_SR", "FM_REVIEW", "RDD_REVIEW"]

WorkflowRole = Literal["MALL_MANAGER", "FM_MANAGER", "DD_ENGINEER"]

ConfirmationStatus = Literal["PENDING", "CONFIRMED", "REJECTED"]

FMDocumentType = Literal[
    "SR_HANDOVER_CHECKLIST",
    "SR_HANDOVER_SITE_SURVEY",
    "SR_COP_CHECKLIST_OTHER",
]

RDDDocumentType = Literal["DR_SR_HANDOVER_REPORT"]

# ── Stage definition dataclass ────────────────────────────────────────────────


@dataclass(frozen=True)
class StageDefinition:
    """Immutable description of a single workflow stage."""

    stage: str
    role: str
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...] = field(default_factory=tuple)


# ── Stage instances ───────────────────────────────────────────────────────────

CREATE_SR_STAGE = StageDefinition(
    stage="CREATE_SR",
    role="MALL_MANAGER",
    required_fields=(
        "tenant_profile_id",
        "property_id",
        "lease_code",
        "lease_id",
        "brand_id",
        "mall",
        "brand",
        "unit_codes",
        "city",
        "contracted_area",
        "title",
        "description",
        "startDate",
        "endDate",
        "inspection_done_by",
        "comments",
    ),
)

FM_REVIEW_STAGE = StageDefinition(
    stage="FM_REVIEW",
    role="FM_MANAGER",
    required_fields=(
        "unit_readiness_date",
        "expected_handover_date",
    ),
    required_documents=(
        "SR_HANDOVER_CHECKLIST",
        "SR_HANDOVER_SITE_SURVEY",
        "SR_COP_CHECKLIST_OTHER",
    ),
)

RDD_REVIEW_STAGE = StageDefinition(
    stage="RDD_REVIEW",
    role="DD_ENGINEER",
    required_fields=(
        "guideLineLink",
        "actual_handover_date",
        "fitout_start_date",
        "fitout_end_date",
        "trading_date",
    ),
    required_documents=("DR_SR_HANDOVER_REPORT",),
)

# ── Registry / ordered stage list ────────────────────────────────────────────

STAGE_REGISTRY: dict[str, StageDefinition] = {
    "CREATE_SR": CREATE_SR_STAGE,
    "FM_REVIEW": FM_REVIEW_STAGE,
    "RDD_REVIEW": RDD_REVIEW_STAGE,
}

WORKFLOW_STAGES: tuple[str, ...] = ("CREATE_SR", "FM_REVIEW", "RDD_REVIEW")

# ── Derived field sets ────────────────────────────────────────────────────────

# All fields that the LLM / user may supply across every stage.
ALLOWED_EXTRACTED_FIELDS: frozenset[str] = frozenset(
    CREATE_SR_STAGE.required_fields
    + FM_REVIEW_STAGE.required_fields
    + RDD_REVIEW_STAGE.required_fields
)

# Fields populated from backend APIs (lease lookup, tenant profile, etc.).
# The graph must not ask the user for these; they are resolved programmatically.
BACKEND_DERIVED_FIELDS: frozenset[str] = frozenset(
    {
        "tenant_profile_id",
        "property_id",
        "lease_id",
        "brand_id",
        "mall",
        "brand",
        "unit_codes",
        "city",
        "contracted_area",
    }
)

# Fields that the user / LLM must explicitly supply (not backend-derived).
USER_SUPPLIED_FIELDS: frozenset[str] = ALLOWED_EXTRACTED_FIELDS - BACKEND_DERIVED_FIELDS

# Optional fields: present in the stage's required_fields tuple so the bot
# proactively asks for them, but an empty-string answer is accepted as valid
# (the user may legitimately have nothing to add).  These are excluded from the
# blocking-missing check in get_missing_fields once they carry any value
# (including the empty string that merge_state_node normalises "None" to).
#
# ``description`` is included here because users legitimately respond with
# "no description" — the resulting empty string must not be treated as missing
# and must not block title auto-generation or the confirmation card.
OPTIONAL_FIELDS: frozenset[str] = frozenset({"description", "comments", "notes"})

# ── Document type registries ──────────────────────────────────────────────────

FM_ALLOWED_DOCUMENTS: tuple[str, ...] = FM_REVIEW_STAGE.required_documents

RDD_REQUIRED_DOCUMENTS: tuple[str, ...] = RDD_REVIEW_STAGE.required_documents

ALL_DOCUMENT_TYPES: frozenset[str] = frozenset(
    FM_ALLOWED_DOCUMENTS + RDD_REQUIRED_DOCUMENTS
)

# ── Permission map: role → stages the role may act on ────────────────────────

PERMISSION_MAP: dict[str, tuple[str, ...]] = {
    stage_def.role: (stage_def.stage,) for stage_def in STAGE_REGISTRY.values()
}

# ── Helper utilities ──────────────────────────────────────────────────────────


def get_stage(stage_name: str) -> StageDefinition:
    """Return a ``StageDefinition`` or raise ``KeyError`` for unknown stages."""
    try:
        return STAGE_REGISTRY[stage_name]
    except KeyError:
        valid = ", ".join(WORKFLOW_STAGES)
        raise KeyError(f"Unknown workflow stage '{stage_name}'. Valid: {valid}") from None


def get_required_fields(stage_name: str) -> tuple[str, ...]:
    """Return required fields for *stage_name* — single point of truth for nodes."""
    return get_stage(stage_name).required_fields


def get_required_documents(stage_name: str) -> tuple[str, ...]:
    """Return required document types for *stage_name*."""
    return get_stage(stage_name).required_documents


def get_missing_fields(stage_name: str, collected: dict) -> list[str]:
    """Return required fields absent from *collected* for *stage_name*.

    A field is considered missing when its value is ``None``, ``""``, or
    ``[]``.  Integer ``0`` and boolean ``False`` are treated as valid values,
    consistent with ``validate_required_fields`` in ``validation_service``.

    Optional fields (``OPTIONAL_FIELDS``) are excluded from the missing list
    once the user has explicitly answered them — even with an empty string
    (which ``merge_state_node`` writes when the user declines, e.g. "no
    comments").  A ``None`` value for an optional field still counts as
    missing so the bot still asks proactively on the first pass.
    """

    def _is_missing(value: object) -> bool:
        return value is None or value == "" or value == []

    def _is_missing_for_field(field_name: str, value: object) -> bool:
        if field_name in OPTIONAL_FIELDS:
            # Only missing when the field has never been touched (value is None).
            # An empty string means the user explicitly declined → not missing.
            return value is None
        return _is_missing(value)

    return [
        f
        for f in get_required_fields(stage_name)
        if _is_missing_for_field(f, collected.get(f))
    ]


def role_can_act_on_stage(role: str, stage_name: str) -> bool:
    """True if *role* is permitted to act on *stage_name*."""
    return stage_name in PERMISSION_MAP.get(role, ())


# ── LLM extraction output shape (Pydantic) — legacy ──────────────────────────


class HandoverExtractionSchema(BaseModel):
    """Shape for LLM JSON output — values are proposals until validated in code.

    Kept for backward compatibility.  New code should use
    ``HandoverExtractedFields`` which includes per-field confidence scores.
    """

    summary: str | None = PydanticField(
        default=None,
        description="Short summary of user intent",
    )
    fields: dict[str, str] = PydanticField(
        default_factory=dict,
        description="Proposed field_key → string value (keys must be in ALLOWED_EXTRACTED_FIELDS)",
    )


# ── Field sets for extraction ─────────────────────────────────────────────────

# Fields that the LLM may propose — user-supplied hints that the graph can
# accept and later merge into collected_data.
EXTRACTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "lease_code",
        "mall",
        "brand",
        # "title" is intentionally excluded: the system auto-generates it as
        # "handover-{lease_code}-{description_slug}".  The LLM must not attempt
        # to extract or override it from user input.
        "description",
        "startDate",
        "endDate",
        "inspection_done_by",
        "comments",
        "notes",
        "unit_readiness_date",
        "expected_handover_date",
        "guideLineLink",
        "actual_handover_date",
        "fitout_start_date",
        "fitout_end_date",
        "trading_date",
    }
)

# Fields that must only ever come from backend API lookups.
# The LLM must never populate these; any attempt is silently stripped.
BACKEND_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "tenant_profile_id",
        "property_id",
        "brand_id",
        "lease_id",
        "contract_id",
        "unit_codes",
        "city",
        "contracted_area",
    }
)

InspectionDoneBy = Literal["FM_MANAGER", "OPERATIONS"]


# ── Richer extraction output shape (Pydantic) ─────────────────────────────────


class ExtractedFieldValue(BaseModel):
    """A single extracted field with its proposed value and extraction confidence."""

    value: str = PydanticField(description="Proposed string value for this field.")
    confidence: float = PydanticField(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="LLM confidence that this value is correct (0.0–1.0).",
    )


class HandoverExtractedFields(BaseModel):
    """Rich LLM extraction output: per-field confidence, auto-stripping of forbidden keys.

    The ``model_validator`` silently removes any field that is not in
    ``EXTRACTABLE_FIELDS`` or is present in ``BACKEND_ONLY_FIELDS`` so that
    a hallucinating model can never inject backend-derived IDs into the state.
    """

    summary: str | None = PydanticField(
        default=None,
        description="One-sentence summary of user intent.",
    )
    fields: dict[str, ExtractedFieldValue] = PydanticField(
        default_factory=dict,
        description="Mapping of field_name → {value, confidence}.",
    )

    @model_validator(mode="after")
    def _strip_forbidden_and_unknown_fields(self) -> "HandoverExtractedFields":
        """Remove keys that are not explicitly extractable or are backend-only."""
        self.fields = {
            k: v
            for k, v in self.fields.items()
            if k in EXTRACTABLE_FIELDS and k not in BACKEND_ONLY_FIELDS
        }
        return self

    def to_flat_dict(self) -> dict[str, str]:
        """Return ``{field_name: value}`` without confidence scores."""
        return {k: v.value for k, v in self.fields.items()}

    def to_confidence_dict(self) -> dict[str, float]:
        """Return ``{field_name: confidence}`` scores only."""
        return {k: v.confidence for k, v in self.fields.items()}

    def to_state_dict(self) -> dict[str, dict[str, Any]]:
        """Return the full ``{field: {value, confidence}}`` shape for state storage."""
        return {k: {"value": v.value, "confidence": v.confidence} for k, v in self.fields.items()}


# ── Trace metadata dataclass ──────────────────────────────────────────────────


@dataclass
class ExtractionTraceMeta:
    """Metadata captured during a single FieldExtractionService.extract() call."""

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    parse_success: bool = False
    parse_error: str | None = None
    retry_count: int = 0
    raw_output: dict[str, Any] | None = None
