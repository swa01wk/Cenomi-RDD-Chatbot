import type {
  FeedbackPayload,
  MetricsSummary,
  PaginatedTraceList,
  TraceDetail,
  TraceFiltersState,
} from "@/lib/types/observability";

// Observability trace/session endpoints live under /api (no v1 prefix).
// Only the metrics summary endpoint uses /api/v1.
function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return base.replace(/\/$/, "");
}

function v1Base(): string {
  const prefix = process.env.NEXT_PUBLIC_API_V1_PREFIX ?? "/api/v1";
  return `${apiBase()}${prefix}`;
}

function observabilityBase(): string {
  return `${apiBase()}/api/observability`;
}

// ─── Trace list ───────────────────────────────────────────────────────────────

export async function listTraces(
  filters?: Partial<TraceFiltersState>,
): Promise<PaginatedTraceList> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.agent) params.set("agent", filters.agent);
  if (filters?.intent) params.set("intent", filters.intent);
  if (filters?.user_id) params.set("user_id", filters.user_id);
  if (filters?.date_from) params.set("from_date", filters.date_from);
  if (filters?.date_to) params.set("to_date", filters.date_to);
  if (filters?.error_only) params.set("has_error", "true");
  if (filters?.page) params.set("page", String(filters.page));
  if (filters?.page_size) params.set("page_size", String(filters.page_size));

  const qs = params.toString();
  const url = `${observabilityBase()}/traces${qs ? `?${qs}` : ""}`;

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`listTraces failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PaginatedTraceList;
}

// ─── Trace detail ─────────────────────────────────────────────────────────────

export async function getTraceDetail(traceId: string): Promise<TraceDetail | null> {
  const res = await fetch(`${observabilityBase()}/traces/${traceId}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`getTraceDetail failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as TraceDetail;
}

// ─── Metrics ──────────────────────────────────────────────────────────────────

export async function getMetricsSummary(): Promise<MetricsSummary> {
  const res = await fetch(`${v1Base()}/observability/metrics/summary`, {
    next: { revalidate: 30 },
  });
  if (!res.ok) {
    throw new Error(`getMetricsSummary failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as MetricsSummary;
}

// ─── Feedback ─────────────────────────────────────────────────────────────────

export async function submitFeedback(
  traceId: string,
  body: FeedbackPayload,
): Promise<void> {
  const res = await fetch(`${observabilityBase()}/traces/${traceId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`submitFeedback failed: ${res.status} ${res.statusText}`);
  }
}
