"use client";

import { useEffect, useState } from "react";
import type { ConfirmationField, ResponseUIConfirmationCard } from "@/lib/types/chat";

type Props = {
  data: ResponseUIConfirmationCard;
  onConfirm: (fields: Record<string, unknown>) => void;
  onCancel: () => void;
  /** When true, field inputs and action buttons are hidden (past-turn view). */
  readOnly?: boolean;
};

function FieldRow({
  field,
  editedValue,
  onChange,
  readOnly,
}: {
  field: ConfirmationField;
  editedValue: string;
  onChange: (val: string) => void;
  readOnly?: boolean;
}) {
  const displayValue =
    field.value === null || field.value === undefined ? "—" : String(field.value);

  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <span className="shrink-0 text-xs font-medium text-zinc-500 dark:text-zinc-400">
        {field.label}
      </span>
      {field.editable && !readOnly ? (
        <input
          type="text"
          value={editedValue}
          onChange={(e) => onChange(e.target.value)}
          className="w-1/2 rounded border border-zinc-300 bg-transparent px-2 py-1 text-right text-xs outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-500/20 dark:border-zinc-700"
        />
      ) : (
        <span className="text-right text-xs text-zinc-800 dark:text-zinc-100">
          {field.editable ? editedValue || displayValue : displayValue}
        </span>
      )}
    </div>
  );
}

export function ServiceRequestSummaryCard({ data, onConfirm, onCancel, readOnly = false }: Props) {
  const [editedFields, setEditedFields] = useState<Record<string, string>>({});

  // Reset editable-field values whenever the backing data changes (e.g. after
  // the backend returns an updated confirmation_card with corrected values).
  useEffect(() => {
    const init: Record<string, string> = {};
    data.fields.forEach((f) => {
      if (f.editable) {
        init[f.key] = f.value === null || f.value === undefined ? "" : String(f.value);
      }
    });
    setEditedFields(init);
  }, [data.fields]);

  function handleConfirm() {
    const merged: Record<string, unknown> = {};
    data.fields.forEach((f) => {
      merged[f.key] = f.editable ? (editedFields[f.key] ?? f.value) : f.value;
    });
    onConfirm(merged);
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Review & Confirm
        </h2>
        {data.requestType && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
            {data.requestType}
          </span>
        )}
      </div>
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{data.message}</p>
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {data.fields.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            editedValue={editedFields[field.key] ?? ""}
            onChange={(val) => setEditedFields((prev) => ({ ...prev, [field.key]: val }))}
            readOnly={readOnly}
          />
        ))}
      </div>
      {!readOnly && (
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={handleConfirm}
            className="flex-1 rounded-md bg-blue-600 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
          >
            Confirm & Submit
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-md border border-zinc-300 py-2 text-sm font-medium text-zinc-600 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            Make Changes
          </button>
        </div>
      )}
    </div>
  );
}
