"use client";

import { useState } from "react";

// ─── Field display config ─────────────────────────────────────────────────────

type FieldConfig = {
  key: string;
  label: string;
};

const FM_REVIEW_FIELDS: FieldConfig[] = [
  { key: "mall", label: "Mall" },
  { key: "brand", label: "Brand" },
  { key: "unit_code", label: "Unit Code" },
  { key: "lease_code", label: "Lease Code" },
  { key: "description", label: "Description" },
];

const RDD_REVIEW_ADDITIONAL_FIELDS: FieldConfig[] = [
  { key: "unit_readiness_date", label: "Unit Readiness Date" },
  { key: "expected_handover_date", label: "Expected Handover Date" },
];

function getFieldsForStage(stage: string): FieldConfig[] {
  if (stage === "FM_REVIEW") return FM_REVIEW_FIELDS;
  if (stage === "RDD_REVIEW") return [...FM_REVIEW_FIELDS, ...RDD_REVIEW_ADDITIONAL_FIELDS];
  return [];
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface StageContextPanelProps {
  workflowStage: string | null | undefined;
  collectedData: Record<string, string> | null | undefined;
  srId: string | null | undefined;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function StageContextPanel({
  workflowStage,
  collectedData,
  srId,
}: StageContextPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const shouldShow =
    (workflowStage === "FM_REVIEW" || workflowStage === "RDD_REVIEW") && srId;

  if (!shouldShow) return null;

  const fields = getFieldsForStage(workflowStage!);
  const hasData = collectedData && Object.keys(collectedData).length > 0;

  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800/50">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
          SR Context{srId ? ` — ${srId}` : ""}
        </span>
        <svg
          className={`h-4 w-4 text-zinc-400 transition-transform dark:text-zinc-500 ${
            expanded ? "rotate-180" : ""
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Content — shown when expanded */}
      {expanded && (
        <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-700">
          {!hasData ? (
            <p className="text-xs text-zinc-400 dark:text-zinc-500">
              No context data available yet.
            </p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
              {fields.map(({ key, label }) => {
                const value = collectedData?.[key];
                if (!value) return null;
                return (
                  <div key={key} className="col-span-1">
                    <dt className="text-[10px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                      {label}
                    </dt>
                    <dd className="mt-0.5 text-xs text-zinc-700 dark:text-zinc-200">
                      {value}
                    </dd>
                  </div>
                );
              })}
            </dl>
          )}
        </div>
      )}
    </div>
  );
}
