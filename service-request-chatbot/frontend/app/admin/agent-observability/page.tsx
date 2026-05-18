"use client";

import { useCallback, useEffect, useState } from "react";
import { MetricsCards } from "@/components/observability/MetricsCards";
import { TraceFilters } from "@/components/observability/TraceFilters";
import { TraceListTable } from "@/components/observability/TraceListTable";
import { listTraces } from "@/lib/api/observability-client";
import { DEFAULT_FILTERS, type PaginatedTraceList, type TraceFiltersState } from "@/lib/types/observability";

export default function AgentObservabilityPage() {
  const [filters, setFilters] = useState<TraceFiltersState>(DEFAULT_FILTERS);
  const [data, setData] = useState<PaginatedTraceList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTraces = useCallback(async (f: TraceFiltersState) => {
    setLoading(true);
    setError(null);
    try {
      const result = await listTraces(f);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTraces(filters);
  }, [filters, fetchTraces]);

  function handleFiltersChange(next: TraceFiltersState) {
    setFilters(next);
  }

  function handlePageChange(page: number) {
    setFilters((f) => ({ ...f, page }));
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agent Observability</h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Auditable trace and state transitions for every bot interaction. Debug why the
            agent asked, extracted, or submitted something.
          </p>
        </div>
        <button
          type="button"
          onClick={() => fetchTraces(filters)}
          disabled={loading}
          className="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {/* Metrics are server-rendered via an async Server Component */}
      <MetricsCards />

      <TraceFilters filters={filters} onChange={handleFiltersChange} loading={loading} />

      <TraceListTable
        data={data}
        loading={loading}
        error={error}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
