"use client";

import Link from "next/link";
import { useState } from "react";
import type { PaginatedTraceList, TraceSummary } from "@/lib/types/observability";

type Props = {
  data: PaginatedTraceList | null;
  loading?: boolean;
  error?: string | null;
  onPageChange?: (page: number) => void;
};

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  error: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

function statusBadge(status: string) {
  const cls = STATUS_BADGE[status] ?? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

function fmt(ms: number | null): string {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms} ms`;
}

function fmtCost(cost: string | null): string {
  if (!cost) return "—";
  const n = parseFloat(cost);
  return isNaN(n) ? "—" : `$${n.toFixed(4)}`;
}

function shortId(id: string): string {
  return id.slice(0, 8) + "…";
}

function fmtDate(d: string): string {
  try {
    return new Date(d).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d;
  }
}

function groupBySession(items: TraceSummary[]): Map<string, TraceSummary[]> {
  const map = new Map<string, TraceSummary[]>();
  for (const t of items) {
    const existing = map.get(t.session_id);
    if (existing) {
      existing.push(t);
    } else {
      map.set(t.session_id, [t]);
    }
  }
  return map;
}

function sessionAggregates(traces: TraceSummary[]) {
  const totalLatency = traces.some((t) => t.total_latency_ms !== null)
    ? traces.reduce((sum, t) => sum + (t.total_latency_ms ?? 0), 0)
    : null;
  const totalTokens = traces.some((t) => t.total_token_count !== null)
    ? traces.reduce((sum, t) => sum + (t.total_token_count ?? 0), 0)
    : null;
  const totalCost = traces.some((t) => t.estimated_cost !== null)
    ? traces
        .reduce((sum, t) => sum + (t.estimated_cost ? parseFloat(t.estimated_cost) : 0), 0)
        .toFixed(4)
    : null;

  const hasError = traces.some((t) => t.status === "error" || t.status === "failed");
  const allDone = traces.every((t) => t.status === "completed");
  const anyRunning = traces.some((t) => t.status === "running");
  const sessionStatus = hasError ? "failed" : anyRunning ? "running" : allDone ? "completed" : "pending";

  return { totalLatency, totalTokens, totalCost, sessionStatus };
}

type SessionRowProps = {
  sessionId: string;
  traces: TraceSummary[];
  isExpanded: boolean;
  onToggle: () => void;
};

function SessionGroupRows({ sessionId, traces, isExpanded, onToggle }: SessionRowProps) {
  const { totalLatency, totalTokens, totalCost, sessionStatus } = sessionAggregates(traces);
  const representativeUser = traces[0]?.user_id ?? "";
  const firstCreated = traces[traces.length - 1]?.created_at;
  const lastCreated = traces[0]?.created_at;

  return (
    <>
      {/* Session header row */}
      <tr
        className="bg-zinc-50 dark:bg-zinc-800/70 cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
        onClick={onToggle}
      >
        {/* Toggle + Session ID */}
        <td className="px-3 py-2.5" colSpan={2}>
          <div className="flex items-center gap-2">
            <span className="text-zinc-400 dark:text-zinc-500 text-xs select-none w-3 shrink-0">
              {isExpanded ? "▼" : "▶"}
            </span>
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-xs font-semibold text-zinc-700 dark:text-zinc-200" title={sessionId}>
                {shortId(sessionId)}
              </span>
              <span className="text-[10px] text-zinc-400 dark:text-zinc-500">
                {traces.length} trace{traces.length !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
        </td>

        {/* User */}
        <td className="px-3 py-2.5">
          <span className="font-mono text-xs text-zinc-500" title={representativeUser}>
            {shortId(representativeUser)}
          </span>
        </td>

        {/* Intent — blank at session level */}
        <td className="px-3 py-2.5 text-zinc-400 text-xs">—</td>

        {/* Active Agent — blank at session level */}
        <td className="px-3 py-2.5 text-zinc-400 text-xs">—</td>

        {/* Workflow Stage — show time range */}
        <td className="px-3 py-2.5 text-[10px] text-zinc-400 whitespace-nowrap">
          {firstCreated && lastCreated && firstCreated !== lastCreated ? (
            <span title={`First: ${firstCreated}\nLast: ${lastCreated}`}>
              {fmtDate(firstCreated)} → {fmtDate(lastCreated)}
            </span>
          ) : firstCreated ? (
            fmtDate(firstCreated)
          ) : (
            "—"
          )}
        </td>

        {/* Status */}
        <td className="px-3 py-2.5 whitespace-nowrap">
          {statusBadge(sessionStatus)}
        </td>

        {/* Latency */}
        <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
          {fmt(totalLatency)}
        </td>

        {/* Tokens */}
        <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
          {totalTokens !== null ? totalTokens.toLocaleString() : "—"}
        </td>

        {/* Cost */}
        <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
          {totalCost ? `$${totalCost}` : "—"}
        </td>

        {/* Created At — show range */}
        <td className="px-3 py-2.5 whitespace-nowrap text-xs text-zinc-500">
          {firstCreated ? fmtDate(firstCreated) : "—"}
        </td>
      </tr>

      {/* Individual trace rows (shown only when expanded) */}
      {isExpanded &&
        traces.map((t, idx) => (
          <tr
            key={t.id}
            className={`hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors ${
              idx === traces.length - 1
                ? "border-b-2 border-zinc-200 dark:border-zinc-700"
                : ""
            }`}
          >
            {/* Indent + Trace ID */}
            <td className="py-2.5 pl-8 pr-3">
              <Link
                href={`/admin/agent-observability/traces/${t.id}`}
                className="font-mono text-xs text-blue-600 hover:underline dark:text-blue-400"
                title={t.id}
              >
                {shortId(t.id)}
              </Link>
            </td>

            {/* Session ID — de-emphasised since it's shown in group header */}
            <td className="px-3 py-2.5">
              <span className="font-mono text-xs text-zinc-300 dark:text-zinc-600" title={t.session_id}>
                {shortId(t.session_id)}
              </span>
            </td>

            <td className="px-3 py-2.5">
              <span className="font-mono text-xs text-zinc-500" title={t.user_id}>
                {shortId(t.user_id)}
              </span>
            </td>
            <td className="px-3 py-2.5 max-w-[140px] truncate text-zinc-700 dark:text-zinc-300" title={t.intent ?? ""}>
              {t.intent ?? <span className="text-zinc-400">—</span>}
            </td>
            <td className="px-3 py-2.5 whitespace-nowrap">
              {t.active_agent ? (
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-mono text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                  {t.active_agent}
                </span>
              ) : (
                <span className="text-zinc-400">—</span>
              )}
            </td>
            <td className="px-3 py-2.5 text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
              {t.trace_type ?? <span className="text-zinc-400">—</span>}
            </td>
            <td className="px-3 py-2.5 whitespace-nowrap">{statusBadge(t.status)}</td>
            <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
              {fmt(t.total_latency_ms)}
            </td>
            <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
              {t.total_token_count !== null ? t.total_token_count.toLocaleString() : "—"}
            </td>
            <td className="px-3 py-2.5 text-right tabular-nums text-xs text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
              {fmtCost(t.estimated_cost)}
            </td>
            <td className="px-3 py-2.5 whitespace-nowrap text-xs text-zinc-500">
              {fmtDate(t.created_at)}
            </td>
          </tr>
        ))}
    </>
  );
}

export function TraceListTable({ data, loading, error, onPageChange }: Props) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
        Failed to load traces: {error}
      </div>
    );
  }

  const items = data?.items ?? [];
  const sessionGroups = groupBySession(items);
  const sessionIds = Array.from(sessionGroups.keys());

  function toggleSession(sessionId: string) {
    setExpandedSessions((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  }

  function expandAll() {
    setExpandedSessions(new Set(sessionIds));
  }

  function collapseAll() {
    setExpandedSessions(new Set());
  }

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      {/* Toolbar */}
      {items.length > 0 && (
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          <span>
            {sessionIds.length} session{sessionIds.length !== 1 ? "s" : ""} · {items.length} trace{items.length !== 1 ? "s" : ""}
          </span>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={expandAll}
              className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
            >
              Expand all
            </button>
            <button
              type="button"
              onClick={collapseAll}
              className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
            >
              Collapse all
            </button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] border-collapse text-left text-sm">
          <thead className="border-b border-zinc-200 bg-zinc-50 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-400">
            <tr>
              <th className="px-3 py-2.5 whitespace-nowrap">Trace ID</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Session ID</th>
              <th className="px-3 py-2.5 whitespace-nowrap">User</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Intent</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Active Agent</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Workflow Stage</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Status</th>
              <th className="px-3 py-2.5 whitespace-nowrap text-right">Latency</th>
              <th className="px-3 py-2.5 whitespace-nowrap text-right">Tokens</th>
              <th className="px-3 py-2.5 whitespace-nowrap text-right">Cost</th>
              <th className="px-3 py-2.5 whitespace-nowrap">Created At</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {loading && items.length === 0 ? (
              <LoadingRows />
            ) : items.length === 0 ? (
              <tr>
                <td
                  colSpan={11}
                  className="px-3 py-8 text-center text-zinc-400 dark:text-zinc-600"
                >
                  No traces found. Adjust filters or wait for new activity.
                </td>
              </tr>
            ) : (
              sessionIds.map((sessionId) => (
                <SessionGroupRows
                  key={sessionId}
                  sessionId={sessionId}
                  traces={sessionGroups.get(sessionId)!}
                  isExpanded={expandedSessions.has(sessionId)}
                  onToggle={() => toggleSession(sessionId)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total > 0 && (
        <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          <span>
            Showing {(data.page - 1) * data.page_size + 1}–
            {Math.min(data.page * data.page_size, data.total)} of{" "}
            {data.total.toLocaleString()} traces
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={data.page <= 1}
              onClick={() => onPageChange?.(data.page - 1)}
              className="rounded border border-zinc-200 px-2 py-1 disabled:opacity-40 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              ← Prev
            </button>
            <button
              type="button"
              disabled={!data.has_next}
              onClick={() => onPageChange?.(data.page + 1)}
              className="rounded border border-zinc-200 px-2 py-1 disabled:opacity-40 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingRows() {
  return (
    <>
      {Array.from({ length: 6 }).map((_, i) => (
        <tr key={i} className="animate-pulse">
          {Array.from({ length: 11 }).map((_, j) => (
            <td key={j} className="px-3 py-3">
              <div className="h-3 rounded bg-zinc-100 dark:bg-zinc-800" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
