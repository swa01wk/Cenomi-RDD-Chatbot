"""Work Permit Service Request — workflow configuration schema.

Defines:
- Stage definition for CREATE_WORK_PERMIT (single-stage workflow)
- Required / backend / optional field sets
- WorkPermitType literal for validation
- get_missing_fields() for the work permit stage
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Final, Literal

# ── Constants ─────────────────────────────────────────────────────────────────

SERVICE_CATEGORY: Final[str] = "WORK_PERMIT"
SUB_CATEGORY: Final[str] = "WORK_PERMIT"

# ── Literal types ─────────────────────────────────────────────────────────────

WorkPermitType = Literal[
    "CONSTRUCTION_HOT",
    "CONSTRUCTION_COLD",
    "CONSTRUCTION_ROOF_ACCESS",
    "MAINTENANCE_HOT",
    "MAINTENANCE_COLD",
    "MAINTENANCE_ROOF_ACCESS",
    "OPERATIONS",
]

VALID_WORK_PERMIT_TYPES: frozenset[str] = frozenset(
    {
        "CONSTRUCTION_HOT",
        "CONSTRUCTION_COLD",
        "CONSTRUCTION_ROOF_ACCESS",
        "MAINTENANCE_HOT",
        "MAINTENANCE_COLD",
        "MAINTENANCE_ROOF_ACCESS",
        "OPERATIONS",
    }
)

WORK_PERMIT_TYPE_LABELS: dict[str, str] = {
    "CONSTRUCTION_HOT": "Construction – Hot Work",
    "CONSTRUCTION_COLD": "Construction – Cold Work",
    "CONSTRUCTION_ROOF_ACCESS": "Construction – Roof Access",
    "MAINTENANCE_HOT": "Maintenance – Hot Work",
    "MAINTENANCE_COLD": "Maintenance – Cold Work",
    "MAINTENANCE_ROOF_ACCESS": "Maintenance – Roof Access",
    "OPERATIONS": "Operations",
}

# ── Stage definition dataclass (mirrors handover_schema pattern) ──────────────


@dataclass(frozen=True)
class WorkPermitStageDefinition:
    """Immutable description of the work permit workflow stage."""

    stage: str
    role: str
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...] = dc_field(default_factory=tuple)


# ── Stage instance ────────────────────────────────────────────────────────────

CREATE_WORK_PERMIT_STAGE = WorkPermitStageDefinition(
    stage="CREATE_WORK_PERMIT",
    role="MALL_MANAGER",
    required_fields=(
        # Backend-derived via lease lookup
        "lease_code",
        "lease_id",
        "property_id",
        "unit_codes",
        "mall",
        "brand",
        # User-supplied
        "work_permit_type",
        "description",
        "start_date",
        "end_date",
        # Optional (empty string accepted)
        "contractor_name",
        "comments",
    ),
)

STAGE_REGISTRY: dict[str, WorkPermitStageDefinition] = {
    "CREATE_WORK_PERMIT": CREATE_WORK_PERMIT_STAGE,
}

# ── Field sets ────────────────────────────────────────────────────────────────

# Resolved by lease lookup — never asked of the user directly.
BACKEND_DERIVED_FIELDS: frozenset[str] = frozenset(
    {
        "lease_id",
        "property_id",
        "unit_codes",
        "mall",
        "brand",
        "tenant_profile_id",
        "city",
        "contracted_area",
    }
)

# User must explicitly supply these (not backend-derived).
USER_SUPPLIED_FIELDS: frozenset[str] = frozenset(
    {
        "lease_code",
        "work_permit_type",
        "description",
        "start_date",
        "end_date",
        "contractor_name",
        "comments",
    }
)

# Fields the LLM extraction service may extract from user messages.
EXTRACTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "lease_code",
        "work_permit_type",
        "description",
        "start_date",
        "end_date",
        "contractor_name",
        "comments",
        "notes",
    }
)

# Backend-only fields that the LLM must never propose.
BACKEND_ONLY_FIELDS: frozenset[str] = BACKEND_DERIVED_FIELDS

# Optional fields: empty string is a valid explicit answer (user may decline).
OPTIONAL_FIELDS: frozenset[str] = frozenset({"contractor_name", "comments", "notes", "description"})

# Auto-generated fields — excluded from user-facing missing-field prompts.
AUTO_GENERATED_FIELDS: frozenset[str] = frozenset()

# ── Helper utilities ──────────────────────────────────────────────────────────


def get_required_fields(stage_name: str) -> tuple[str, ...]:
    """Return required fields for *stage_name*."""
    stage = STAGE_REGISTRY.get(stage_name)
    if not stage:
        raise KeyError(f"Unknown work permit stage '{stage_name}'")
    return stage.required_fields


def get_missing_fields(stage_name: str, collected: dict[str, Any]) -> list[str]:
    """Return required fields absent from *collected* for *stage_name*.

    Mirrors handover_schema.get_missing_fields logic: None/empty-string/empty-list
    is missing for non-optional fields; only None is missing for optional fields.
    """

    def _is_missing(field_name: str, value: Any) -> bool:
        if field_name in OPTIONAL_FIELDS:
            return value is None
        return value is None or value == "" or value == []

    return [
        f
        for f in get_required_fields(stage_name)
        if _is_missing(f, collected.get(f))
    ]
