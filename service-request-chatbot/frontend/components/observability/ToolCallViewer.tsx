"use client";

import { useState } from "react";
import type { ToolCall } from "@/lib/types/observability";

type Props = { toolCalls: ToolCall[] };

const TOOL_TYPE_BADGE: Record<string, string> = {
  api: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  validation: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  search: "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300",
  retrieval: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
};

function fmtLatency(ms: number | null): string {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms} ms`;
}

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-zinc-50 p-3 font-mono text-xs text-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function ToolCallRow({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const typeCls =
    TOOL_TYPE_BADGE[call.tool_type] ??
    "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  const successBadge = call.success === null
    ? null
    : call.success
    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
    : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300";

  return (
    <div className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
            {call.tool_name}
          </span>
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${typeCls}`}>
            {call.tool_type}
          </span>
          {call.status_code !== null && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-mono font-medium ${
                call.status_code >= 200 && call.status_code < 300
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
                  : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
              }`}
            >
              {call.status_code}
            </span>
          )}
          {successBadge && (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${successBadge}`}>
              {call.success ? "success" : "failure"}
            </span>
          )}
          <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
            {fmtLatency(call.latency_ms)}
          </span>
        </div>
        <span className="shrink-0 text-xs text-zinc-400">{open ? "▲" : "▼"}</span>
      </button>

      {call.error_message && (
        <div className="px-4 pb-2">
          <p className="rounded border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
            {call.error_message}
          </p>
        </div>
      )}

      {open && (
        <div className="grid gap-2 px-4 pb-4 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Request
            </p>
            <JsonBlock data={call.request_payload} />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              Response
            </p>
            <JsonBlock data={call.response_payload} />
          </div>
        </div>
      )}
    </div>
  );
}

export function ToolCallViewer({ toolCalls }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Tool Calls</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {toolCalls.length} call{toolCalls.length !== 1 ? "s" : ""} — API, validation, and
          retrieval spans
        </p>
      </div>

      {toolCalls.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-zinc-400 dark:text-zinc-600">
          No tool calls recorded for this trace.
        </p>
      ) : (
        <div>
          {toolCalls.map((call) => (
            <ToolCallRow key={call.id} call={call} />
          ))}
        </div>
      )}
    </div>
  );
}
