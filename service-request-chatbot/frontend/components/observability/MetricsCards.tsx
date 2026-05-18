"use client";

import { useEffect, useState } from "react";
import { getMetricsSummary } from "@/lib/api/observability-client";
import type { MetricsSummary } from "@/lib/types/observability";

const CARD_DEFS: {
  key: keyof MetricsSummary;
  label: string;
  format: (v: number) => string;
  color: string;
}[] = [
  {
    key: "total_traces",
    label: "Total Traces",
    format: (v) => v.toLocaleString(),
    color: "text-zinc-900 dark:text-zinc-100",
  },
  {
    key: "success_rate",
    label: "Success Rate",
    format: (v) => `${(v * 100).toFixed(1)}%`,
    color: "text-emerald-600 dark:text-emerald-400",
  },
  {
    key: "avg_latency_ms",
    label: "Avg Latency",
    format: (v) => `${Math.round(v).toLocaleString()} ms`,
    color: "text-zinc-900 dark:text-zinc-100",
  },
  {
    key: "total_tokens",
    label: "Total Tokens",
    format: (v) => v.toLocaleString(),
    color: "text-zinc-900 dark:text-zinc-100",
  },
  {
    key: "total_cost",
    label: "Est. Cost",
    format: (v) => `$${v.toFixed(4)}`,
    color: "text-zinc-900 dark:text-zinc-100",
  },
  {
    key: "failed_traces",
    label: "Failed Traces",
    format: (v) => v.toLocaleString(),
    color: "text-red-600 dark:text-red-400",
  },
];

export function MetricsCards() {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);

  useEffect(() => {
    getMetricsSummary()
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, []);

  return (
    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {CARD_DEFS.map(({ key, label, format, color }) => {
        const raw = metrics?.[key];
        const value = typeof raw === "number" ? format(raw) : "—";
        return (
          <div
            key={key}
            className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              {label}
            </p>
            <p
              className={`text-xl font-semibold tabular-nums ${
                metrics === null ? "animate-pulse text-zinc-300 dark:text-zinc-700" : color
              }`}
            >
              {value}
            </p>
          </div>
        );
      })}
    </div>
  );
}
