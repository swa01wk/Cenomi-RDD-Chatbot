"use client";

import { useState } from "react";
import type { LLMCall } from "@/lib/types/observability";

type Props = { llmCalls: LLMCall[] };

function fmtLatency(ms: number | null): string {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms} ms`;
}

function fmtCost(cost: string | null): string {
  if (!cost) return "—";
  const n = parseFloat(cost);
  return isNaN(n) ? "—" : `$${n.toFixed(5)}`;
}

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded bg-zinc-50 p-3 font-mono text-xs text-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function TokenBar({ input, output, total }: { input: number | null; output: number | null; total: number | null }) {
  if (!total || total === 0) return null;
  const inPct = input ? Math.round((input / total) * 100) : 0;
  const outPct = output ? Math.round((output / total) * 100) : 0;
  return (
    <div className="mt-1 flex gap-1 text-[10px] text-zinc-500 dark:text-zinc-400">
      <span className="rounded bg-blue-100 px-1 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
        in {input?.toLocaleString() ?? "—"} ({inPct}%)
      </span>
      <span className="rounded bg-emerald-100 px-1 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
        out {output?.toLocaleString() ?? "—"} ({outPct}%)
      </span>
      <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
        total {total.toLocaleString()}
      </span>
    </div>
  );
}

function LLMCallRow({ call }: { call: LLMCall }) {
  const [open, setOpen] = useState(false);

  const parseBadgeCls =
    call.parse_success === null
      ? ""
      : call.parse_success
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
      : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300";

  return (
    <div className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {/* Provider + model */}
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              {call.provider ?? "unknown"} / {call.model ?? "unknown"}
            </span>
            {call.prompt_name && (
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                {call.prompt_name}
                {call.prompt_version ? ` v${call.prompt_version}` : ""}
              </span>
            )}
            {call.parse_success !== null && (
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${parseBadgeCls}`}>
                {call.parse_success ? "parsed" : "parse failed"}
              </span>
            )}
            <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
              {fmtLatency(call.latency_ms)}
            </span>
            <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
              {fmtCost(call.estimated_cost)}
            </span>
          </div>
          <TokenBar
            input={call.input_tokens}
            output={call.output_tokens}
            total={call.total_tokens}
          />
        </div>
        <span className="mt-0.5 shrink-0 text-xs text-zinc-400">{open ? "▲" : "▼"}</span>
      </button>

      {call.parse_error && (
        <div className="px-4 pb-2">
          <p className="rounded border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
            Parse error: {call.parse_error}
          </p>
        </div>
      )}

      {open && Object.keys(call.structured_output).length > 0 && (
        <div className="px-4 pb-4">
          <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Structured Output
          </p>
          <JsonBlock data={call.structured_output} />
        </div>
      )}
    </div>
  );
}

export function LLMCallViewer({ llmCalls }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">LLM Calls</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {llmCalls.length} call{llmCalls.length !== 1 ? "s" : ""} — model, tokens, cost,
          and structured output only (no prompt text)
        </p>
      </div>

      {llmCalls.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-zinc-400 dark:text-zinc-600">
          No LLM calls recorded for this trace.
        </p>
      ) : (
        <div>
          {llmCalls.map((call) => (
            <LLMCallRow key={call.id} call={call} />
          ))}
        </div>
      )}
    </div>
  );
}
