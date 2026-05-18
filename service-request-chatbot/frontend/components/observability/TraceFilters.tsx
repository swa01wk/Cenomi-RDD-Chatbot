"use client";

import type { TraceFiltersState } from "@/lib/types/observability";

const STATUS_OPTIONS = ["", "pending", "running", "completed", "failed", "error"];
const AGENT_OPTIONS = [
  "",
  "intake_agent",
  "clarification_agent",
  "validation_agent",
  "submission_agent",
  "escalation_agent",
];
const STAGE_OPTIONS = [
  "",
  "intake",
  "clarification",
  "validation",
  "confirmation",
  "submission",
  "complete",
  "escalated",
];

type Props = {
  filters: TraceFiltersState;
  onChange: (next: TraceFiltersState) => void;
  loading?: boolean;
};

export function TraceFilters({ filters, onChange, loading }: Props) {
  function set<K extends keyof TraceFiltersState>(key: K, value: TraceFiltersState[K]) {
    onChange({ ...filters, [key]: value, page: 1 });
  }

  function reset() {
    onChange({
      status: "",
      agent: "",
      intent: "",
      workflow_stage: "",
      user_id: "",
      date_from: "",
      date_to: "",
      error_only: false,
      high_latency: false,
      failed_validation: false,
      api_failure: false,
      page: 1,
      page_size: filters.page_size,
    });
  }

  const hasActive =
    !!filters.status ||
    !!filters.agent ||
    !!filters.intent ||
    !!filters.workflow_stage ||
    !!filters.user_id ||
    !!filters.date_from ||
    !!filters.date_to ||
    filters.error_only ||
    filters.high_latency ||
    filters.failed_validation ||
    filters.api_failure;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Filters</h2>
        {hasActive && (
          <button
            type="button"
            onClick={reset}
            className="text-xs text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Row 1 — dropdowns + text inputs */}
      <div className="flex flex-wrap gap-2">
        <select
          value={filters.status}
          onChange={(e) => set("status", e.target.value)}
          className={selectCls}
          aria-label="Status"
        >
          <option value="">Status</option>
          {STATUS_OPTIONS.filter(Boolean).map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>

        <select
          value={filters.agent}
          onChange={(e) => set("agent", e.target.value)}
          className={selectCls}
          aria-label="Agent"
        >
          <option value="">Agent</option>
          {AGENT_OPTIONS.filter(Boolean).map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={filters.intent}
          onChange={(e) => set("intent", e.target.value)}
          placeholder="Intent"
          className={inputCls}
          aria-label="Intent"
        />

        <select
          value={filters.workflow_stage}
          onChange={(e) => set("workflow_stage", e.target.value)}
          className={selectCls}
          aria-label="Workflow stage"
        >
          <option value="">Stage</option>
          {STAGE_OPTIONS.filter(Boolean).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={filters.user_id}
          onChange={(e) => set("user_id", e.target.value)}
          placeholder="User ID"
          className={inputCls}
          aria-label="User ID"
        />

        <input
          type="date"
          value={filters.date_from}
          onChange={(e) => set("date_from", e.target.value)}
          className={inputCls}
          aria-label="From date"
          title="From date"
        />

        <input
          type="date"
          value={filters.date_to}
          onChange={(e) => set("date_to", e.target.value)}
          className={inputCls}
          aria-label="To date"
          title="To date"
        />
      </div>

      {/* Row 2 — boolean toggles */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
        <CheckFilter
          label="Error only"
          checked={filters.error_only}
          onChange={(v) => set("error_only", v)}
        />
        <CheckFilter
          label="High latency (>5 s)"
          checked={filters.high_latency}
          onChange={(v) => set("high_latency", v)}
        />
        <CheckFilter
          label="Failed validation"
          checked={filters.failed_validation}
          onChange={(v) => set("failed_validation", v)}
        />
        <CheckFilter
          label="API failure"
          checked={filters.api_failure}
          onChange={(v) => set("api_failure", v)}
        />
      </div>

      {loading && (
        <p className="mt-2 text-xs text-zinc-400 dark:text-zinc-500">Updating…</p>
      )}
    </div>
  );
}

function CheckFilter({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-400">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-blue-600"
      />
      {label}
    </label>
  );
}

const selectCls =
  "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-800 " +
  "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-blue-500";

const inputCls =
  "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-800 placeholder:text-zinc-400 " +
  "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-blue-500";
