"use client";

import { useState } from "react";
import type { RunTreeNode } from "@/lib/types/observability";

type Props = { runTree: RunTreeNode[] };

const STATUS_DOT: Record<string, string> = {
  completed: "bg-emerald-500",
  running: "bg-blue-500 animate-pulse",
  pending: "bg-yellow-400",
  failed: "bg-red-500",
  error: "bg-red-500",
};

const RUN_TYPE_BADGE: Record<string, string> = {
  chain: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  llm: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  tool: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  retriever: "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300",
  parser: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  prompt: "bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300",
};

function fmtLatency(ms: number | null): string {
  if (ms === null) return "";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms} ms`;
}

function RunNode({ node, depth = 0 }: { node: RunTreeNode; depth?: number }) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children.length > 0;
  const dotCls = STATUS_DOT[node.status] ?? "bg-zinc-400";
  const typeCls =
    RUN_TYPE_BADGE[node.run_type] ?? "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  const latency = fmtLatency(node.latency_ms);

  return (
    <li>
      <div
        className="group flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
        onClick={() => hasChildren && setOpen((o) => !o)}
        role={hasChildren ? "button" : undefined}
        aria-expanded={hasChildren ? open : undefined}
      >
        {/* Expand toggle */}
        <span className="mt-0.5 w-4 shrink-0 text-center text-xs text-zinc-400">
          {hasChildren ? (open ? "▾" : "▸") : "·"}
        </span>

        {/* Status dot */}
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dotCls}`} />

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              {node.run_name}
            </span>
            {node.node_name && node.node_name !== node.run_name && (
              <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                {node.node_name}
              </span>
            )}
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${typeCls}`}
            >
              {node.run_type}
            </span>
            {latency && (
              <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                {latency}
              </span>
            )}
          </div>
          {node.error_message && (
            <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">
              {node.error_message}
            </p>
          )}
        </div>
      </div>

      {hasChildren && open && (
        <ul className="list-none p-0">
          {node.children.map((child) => (
            <RunNode key={child.id} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function RunTreeViewer({ runTree }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Run Tree</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          LangGraph node execution order and spans
        </p>
      </div>

      {runTree.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-zinc-400 dark:text-zinc-600">
          No run data recorded for this trace.
        </p>
      ) : (
        <ul className="list-none p-2">
          {runTree.map((node) => (
            <RunNode key={node.id} node={node} depth={0} />
          ))}
        </ul>
      )}
    </div>
  );
}
