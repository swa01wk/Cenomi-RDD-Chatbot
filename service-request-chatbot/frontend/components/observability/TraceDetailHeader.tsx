import Link from "next/link";
import type { TraceResponse } from "@/lib/types/observability";

type Props = { trace: TraceResponse };

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  error: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

function fmtDate(d: string | null): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return d;
  }
}

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

function MetaItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {label}
      </p>
      <p className="mt-0.5 truncate text-sm text-zinc-800 dark:text-zinc-200">{value}</p>
    </div>
  );
}

function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-xs">{children}</span>;
}

export function TraceDetailHeader({ trace }: Props) {
  const statusCls =
    STATUS_BADGE[trace.status] ??
    "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <Link
            href="/admin/agent-observability"
            className="text-sm text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          >
            ← All traces
          </Link>
          <span className="text-zinc-300 dark:text-zinc-700">/</span>
          <h1 className="text-base font-semibold">Trace Detail</h1>
        </div>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusCls}`}
        >
          {trace.status}
        </span>
      </div>

      {/* IDs row */}
      <div className="grid gap-4 border-b border-zinc-100 px-4 py-4 sm:grid-cols-3 dark:border-zinc-800">
        <MetaItem label="Trace ID" value={<Mono>{trace.id}</Mono>} />
        <MetaItem label="Session ID" value={<Mono>{trace.session_id}</Mono>} />
        <MetaItem label="User ID" value={<Mono>{trace.user_id}</Mono>} />
      </div>

      {/* Agent / intent / stage row */}
      <div className="grid gap-4 border-b border-zinc-100 px-4 py-4 sm:grid-cols-4 dark:border-zinc-800">
        <MetaItem
          label="Active Agent"
          value={
            trace.active_agent ? (
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                {trace.active_agent}
              </span>
            ) : (
              <span className="text-zinc-400">—</span>
            )
          }
        />
        <MetaItem
          label="Intent"
          value={trace.intent ?? <span className="text-zinc-400">—</span>}
        />
        <MetaItem
          label="Stage Before"
          value={trace.workflow_stage_before ?? <span className="text-zinc-400">—</span>}
        />
        <MetaItem
          label="Stage After"
          value={trace.workflow_stage_after ?? <span className="text-zinc-400">—</span>}
        />
      </div>

      {/* Category / performance row */}
      <div className="grid gap-4 border-b border-zinc-100 px-4 py-4 sm:grid-cols-4 dark:border-zinc-800">
        <MetaItem
          label="Service Category"
          value={trace.service_category ?? <span className="text-zinc-400">—</span>}
        />
        <MetaItem
          label="Sub-category"
          value={trace.sub_category ?? <span className="text-zinc-400">—</span>}
        />
        <MetaItem label="Latency" value={fmtLatency(trace.total_latency_ms)} />
        <MetaItem label="Tokens" value={trace.total_token_count?.toLocaleString() ?? "—"} />
      </div>

      {/* Timestamps row */}
      <div className="grid gap-4 px-4 py-4 sm:grid-cols-3">
        <MetaItem label="Created At" value={fmtDate(trace.created_at)} />
        <MetaItem label="Completed At" value={fmtDate(trace.completed_at)} />
        <MetaItem label="Est. Cost" value={fmtCost(trace.estimated_cost)} />
      </div>

      {/* Error banner */}
      {trace.error_message && (
        <div className="border-t border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/50">
          <p className="text-xs font-medium text-red-700 dark:text-red-400">Error</p>
          <p className="mt-0.5 font-mono text-xs text-red-800 dark:text-red-300">
            {trace.error_message}
          </p>
        </div>
      )}
    </div>
  );
}
