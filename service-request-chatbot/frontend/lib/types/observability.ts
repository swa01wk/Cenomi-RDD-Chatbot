// ─── Primitive helpers ────────────────────────────────────────────────────────

export type TraceStatus = "pending" | "running" | "completed" | "failed" | "error";
export type RunType = "chain" | "llm" | "tool" | "retriever" | "embedding" | "prompt" | "parser" | string;
export type SnapshotType = "before" | "after" | string;
export type FeedbackType = "thumbs" | "rating" | "correction" | "flag" | string;
export type ToolType = "api" | "validation" | "search" | "retrieval" | string;

// ─── Trace list / summary ─────────────────────────────────────────────────────

export type TraceSummary = {
  id: string;
  session_id: string;
  user_id: string;
  trace_type: string;
  active_agent: string | null;
  intent: string | null;
  status: TraceStatus;
  error_message: string | null;
  total_latency_ms: number | null;
  total_token_count: number | null;
  estimated_cost: string | null; // Decimal serialised as string
  created_at: string;
  completed_at: string | null;
};

export type PaginatedTraceList = {
  items: TraceSummary[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
};

// ─── Trace detail ─────────────────────────────────────────────────────────────

export type TraceResponse = {
  id: string;
  session_id: string;
  user_id: string;
  trace_type: string;
  active_agent: string | null;
  intent: string | null;
  service_category: string | null;
  sub_category: string | null;
  workflow_stage_before: string | null;
  workflow_stage_after: string | null;
  input_message: string | null;
  output_message: string | null;
  status: TraceStatus;
  error_message: string | null;
  total_latency_ms: number | null;
  total_token_count: number | null;
  estimated_cost: string | null;
  created_at: string;
  completed_at: string | null;
};

// ─── Run tree ─────────────────────────────────────────────────────────────────

export type RunTreeNode = {
  id: string;
  parent_run_id: string | null;
  run_name: string;
  run_type: RunType;
  node_name: string | null;
  status: TraceStatus;
  error_message: string | null;
  latency_ms: number | null;
  started_at: string;
  completed_at: string | null;
  children: RunTreeNode[];
};

export type RunFlat = {
  id: string;
  trace_id: string;
  parent_run_id: string | null;
  run_name: string;
  run_type: RunType;
  node_name: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  status: TraceStatus;
  error_message: string | null;
  latency_ms: number | null;
  started_at: string;
  completed_at: string | null;
};

// ─── State snapshots & diffs ──────────────────────────────────────────────────

export type StateSnapshot = {
  id: string;
  trace_id: string;
  run_id: string;
  snapshot_type: SnapshotType;
  state: Record<string, unknown>;
  created_at: string;
};

export type StateDiff = {
  id: string;
  trace_id: string;
  run_id: string;
  diff: Record<string, unknown>;
  created_at: string;
};

// ─── LLM calls ────────────────────────────────────────────────────────────────

export type LLMCall = {
  id: string;
  trace_id: string;
  run_id: string;
  provider: string | null;
  model: string | null;
  prompt_name: string | null;
  prompt_version: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  estimated_cost: string | null;
  structured_output: Record<string, unknown>;
  parse_success: boolean | null;
  parse_error: string | null;
  created_at: string;
};

// ─── Tool calls ───────────────────────────────────────────────────────────────

export type ToolCall = {
  id: string;
  trace_id: string;
  run_id: string;
  tool_name: string;
  tool_type: ToolType;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown>;
  status_code: number | null;
  success: boolean | null;
  latency_ms: number | null;
  error_message: string | null;
  created_at: string;
};

// ─── Feedback ─────────────────────────────────────────────────────────────────

export type Feedback = {
  id: string;
  trace_id: string;
  run_id: string | null;
  user_id: string | null;
  feedback_type: FeedbackType;
  score: number | null;
  label: string | null;
  comment: string | null;
  created_at: string;
};

export type FeedbackPayload = {
  score?: number;
  comment?: string;
  feedback_type?: FeedbackType;
  label?: string;
};

// ─── Trace detail (full response) ─────────────────────────────────────────────

export type TraceDetail = {
  trace: TraceResponse;
  runs: RunFlat[];
  run_tree: RunTreeNode[];
  state_snapshots: StateSnapshot[];
  state_diffs: StateDiff[];
  llm_calls: LLMCall[];
  tool_calls: ToolCall[];
  feedback: Feedback[];
};

// ─── Metrics ──────────────────────────────────────────────────────────────────

export type MetricsSummary = {
  total_traces: number;
  completed_traces: number;
  failed_traces: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens: number;
  total_cost: number;
  [key: string]: number;
};

// ─── Filter state ─────────────────────────────────────────────────────────────

export type TraceFiltersState = {
  status: string;
  agent: string;
  intent: string;
  workflow_stage: string;
  user_id: string;
  date_from: string;
  date_to: string;
  error_only: boolean;
  high_latency: boolean;
  failed_validation: boolean;
  api_failure: boolean;
  page: number;
  page_size: number;
};

export const DEFAULT_FILTERS: TraceFiltersState = {
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
  page_size: 25,
};
