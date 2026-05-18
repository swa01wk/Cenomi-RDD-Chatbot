"use client";

import { useState } from "react";
import type { StateDiff, StateSnapshot } from "@/lib/types/observability";

type Props = {
  stateDiffs: StateDiff[];
  stateSnapshots: StateSnapshot[];
};

// Keys that represent meaningful extracted fields — shown in the summary row
const EXTRACTED_FIELDS = [
  "intent",
  "service_category",
  "sub_category",
  "workflow_stage",
  "active_agent",
  "confirmation_status",
  "missing_fields",
];

function getVal(obj: Record<string, unknown>, key: string): string {
  const v = obj[key];
  if (v === undefined || v === null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-zinc-50 p-2 font-mono text-xs text-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function buildBeforeAfterFromSnapshots(
  runId: string,
  snapshots: StateSnapshot[],
): { before: Record<string, unknown> | null; after: Record<string, unknown> | null } {
  const before = snapshots.find((s) => s.run_id === runId && s.snapshot_type === "before");
  const after = snapshots.find((s) => s.run_id === runId && s.snapshot_type === "after");
  return { before: before?.state ?? null, after: after?.state ?? null };
}

function DiffRow({ diff, snapshots }: { diff: StateDiff; snapshots: StateSnapshot[] }) {
  const [open, setOpen] = useState(false);
  const { before, after } = buildBeforeAfterFromSnapshots(diff.run_id, snapshots);
  const changedKeys = Object.keys(diff.diff);
  const hasExtracted = changedKeys.some((k) => EXTRACTED_FIELDS.includes(k));

  return (
    <div className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
      {/* Header row */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-2 px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
      >
        <div className="min-w-0">
          <p className="text-xs font-mono text-zinc-500 dark:text-zinc-400">
            run: {diff.run_id.slice(0, 8)}…
          </p>
          <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
            {changedKeys.length} field{changedKeys.length !== 1 ? "s" : ""} changed:{" "}
            <span className="font-mono">{changedKeys.slice(0, 5).join(", ")}{changedKeys.length > 5 ? "…" : ""}</span>
          </p>
        </div>
        <span className="mt-0.5 text-xs text-zinc-400">{open ? "▲" : "▼"}</span>
      </button>

      {/* Extracted fields summary */}
      {hasExtracted && (
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {EXTRACTED_FIELDS.filter((k) => changedKeys.includes(k)).map((k) => (
            <div
              key={k}
              className="rounded border border-zinc-200 bg-zinc-50 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-800"
            >
              <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                {k.replace(/_/g, " ")}
              </p>
              <p className="mt-0.5 font-mono text-xs text-zinc-700 dark:text-zinc-300">
                {after ? getVal(after, k) : getVal(diff.diff, k)}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Expanded: before/after columns */}
      {open && (
        <div className="grid gap-2 px-4 pb-4 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Before
            </p>
            {before ? (
              <JsonBlock data={before} />
            ) : (
              <p className="text-xs text-zinc-400 italic">Not captured</p>
            )}
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              After
            </p>
            {after ? (
              <JsonBlock data={after} />
            ) : (
              <div>
                <p className="mb-1 text-xs text-zinc-400 italic">
                  Showing diff only
                </p>
                <JsonBlock data={diff.diff} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function StateDiffViewer({ stateDiffs, stateSnapshots }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
          State Transitions
        </h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Extracted fields and state changes between agent nodes
        </p>
      </div>

      {stateDiffs.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-zinc-400 dark:text-zinc-600">
          No state diffs recorded for this trace.
        </p>
      ) : (
        <div>
          {stateDiffs.map((diff) => (
            <DiffRow key={diff.id} diff={diff} snapshots={stateSnapshots} />
          ))}
        </div>
      )}
    </div>
  );
}
