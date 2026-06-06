"use client";

import { useState } from "react";
import type { PreviewField, ResponseUISRPreviewCard } from "@/lib/types/chat";

// ---------------------------------------------------------------------------
// Whitelist — only these field keys are shown to the user.
// Internal/system fields (title, brand_id, lease_id, contract_id,
// property_id, tenant_profile_id, lease_brand_or_mall, etc.) are excluded.
// Keep in sync with _PREVIEW_FIELD_ORDER in backend/preview_node.py.
// ---------------------------------------------------------------------------

const DISPLAY_FIELD_KEYS = new Set([
  "lease_code",
  "brand",
  "mall",
  "city",
  "unit_codes",
  "contracted_area",
  "description",
  "startDate",
  "endDate",
  "inspection_done_by",
  "unit_readiness_date",
  "expected_handover_date",
  "actual_handover_date",
  "fitout_start_date",
  "fitout_end_date",
  "trading_date",
  "comments",
  "guideLineLink",
]);

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  SUBMITTED:        "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  IN_PROCESS:       "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300",
  APPROVED:         "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  COMPLETED:        "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  REPORT_SUBMITTED: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  DRAFT:            "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  REJECTED:         "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

function StatusBadge({ status }: { status: string }) {
  const cls =
    STATUS_STYLES[status.toUpperCase()] ??
    "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${cls}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Field row — display mode
// ---------------------------------------------------------------------------

function FieldRow({ field }: { field: PreviewField }) {
  const isEmpty = field.value === null || field.value === undefined || field.value === "";
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <span className="shrink-0 text-xs font-medium text-zinc-500 dark:text-zinc-400">
        {field.label}
      </span>
      <span
        className={`text-right text-xs ${
          isEmpty
            ? "italic text-zinc-400 dark:text-zinc-600"
            : "text-zinc-800 dark:text-zinc-100"
        }`}
      >
        {isEmpty ? "—" : field.value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field row — edit mode
// ---------------------------------------------------------------------------

function EditableFieldRow({
  field,
  value,
  onChange,
}: {
  field: PreviewField;
  value: string;
  onChange: (key: string, val: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="shrink-0 text-xs font-medium text-zinc-500 dark:text-zinc-400">
        {field.label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(field.key, e.target.value)}
        className="min-w-0 flex-1 rounded border border-zinc-300 bg-white px-2 py-0.5 text-right text-xs text-zinc-800 focus:border-blue-500 focus:outline-none dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

type Props = {
  data: ResponseUISRPreviewCard;
  /**
   * When provided and the SR is not yet submitted, the card shows an Edit
   * button.  Clicking Save calls onSave with the mutated field map so the
   * parent can send corrections to the backend.
   */
  onSave?: (changes: Record<string, string>) => void;
};

export function SRPreviewCard({ data, onSave }: Props) {
  // Apply client-side whitelist so internal/system fields never render
  // even if they slip through from the API.
  const fields = data.fields.filter((f) => DISPLAY_FIELD_KEYS.has(f.key));
  const hasFields = fields.length > 0;
  const canEdit = !data.isSubmitted && !!onSave;

  // Local edit state — populated from current field values when entering edit mode.
  const [isEditing, setIsEditing] = useState(false);
  const [pendingEdits, setPendingEdits] = useState<Record<string, string>>({});

  function startEditing() {
    const initial: Record<string, string> = {};
    for (const f of fields) {
      initial[f.key] = f.value ?? "";
    }
    setPendingEdits(initial);
    setIsEditing(true);
  }

  function cancelEditing() {
    setPendingEdits({});
    setIsEditing(false);
  }

  function saveEditing() {
    // Only send keys whose values differ from the original.
    const changes: Record<string, string> = {};
    for (const f of fields) {
      const edited = pendingEdits[f.key] ?? "";
      if (edited !== (f.value ?? "")) {
        changes[f.key] = edited;
      }
    }
    // Also include any keys in pendingEdits not in fields (shouldn't happen but safe).
    for (const [k, v] of Object.entries(pendingEdits)) {
      if (!(k in changes) && v !== "") {
        const original = fields.find((f) => f.key === k)?.value ?? "";
        if (v !== original) changes[k] = v;
      }
    }
    onSave?.(changes);
    setIsEditing(false);
    setPendingEdits({});
  }

  function handleFieldChange(key: string, val: string) {
    setPendingEdits((prev) => ({ ...prev, [key]: val }));
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      {/* Header */}
      <div className="mb-1 flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          {data.isSubmitted ? "Service Request" : "Draft Preview"}
        </h2>
        <div className="flex items-center gap-2">
          {data.requestType && (
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
              {data.requestType}
            </span>
          )}
          {data.status && <StatusBadge status={data.status} />}
          {canEdit && !isEditing && (
            <button
              type="button"
              onClick={startEditing}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-blue-600 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/20"
            >
              Edit
            </button>
          )}
        </div>
      </div>

      {/* SR ID row */}
      {data.srId && (
        <p className="mb-3 font-mono text-[11px] text-zinc-400 dark:text-zinc-500">
          ID: {data.srId}
        </p>
      )}

      {/* Fields */}
      {hasFields ? (
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {fields.map((field) =>
            isEditing ? (
              <EditableFieldRow
                key={field.key}
                field={field}
                value={pendingEdits[field.key] ?? field.value ?? ""}
                onChange={handleFieldChange}
              />
            ) : (
              <FieldRow key={field.key} field={field} />
            ),
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs italic text-zinc-400 dark:text-zinc-600">
          No details collected yet.
        </p>
      )}

      {/* Edit-mode Save / Cancel buttons */}
      {isEditing && (
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={cancelEditing}
            className="rounded px-3 py-1 text-xs font-medium text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={saveEditing}
            className="rounded bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700"
          >
            Save Changes
          </button>
        </div>
      )}

      {/* Footer hint for draft (non-edit mode) */}
      {!data.isSubmitted && hasFields && !isEditing && (
        <p className="mt-3 text-[11px] text-zinc-400 dark:text-zinc-500">
          {canEdit
            ? "Draft — click Edit to update fields, or send a message to make changes."
            : "This is a draft — not yet submitted to the platform."}
        </p>
      )}
    </div>
  );
}
