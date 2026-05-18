import type { ToolCall, TraceResponse } from "@/lib/types/observability";

type ValidationIssue = {
  field?: string;
  message?: string;
  code?: string;
};

type ParsedValidation = {
  valid: boolean;
  issues: ValidationIssue[];
  rule?: string;
};

function parseValidationPayload(payload: Record<string, unknown>): ParsedValidation {
  // Try common shapes returned by validation tool calls
  const valid = Boolean(payload.valid ?? payload.success ?? payload.passed ?? payload.is_valid);
  let issues: ValidationIssue[] = [];

  if (Array.isArray(payload.issues)) {
    issues = (payload.issues as unknown[]).map((i) =>
      typeof i === "string" ? { message: i } : (i as ValidationIssue),
    );
  } else if (Array.isArray(payload.errors)) {
    issues = (payload.errors as unknown[]).map((e) =>
      typeof e === "string" ? { message: e } : (e as ValidationIssue),
    );
  } else if (Array.isArray(payload.validation_errors)) {
    issues = (payload.validation_errors as unknown[]).map((e) =>
      typeof e === "string" ? { message: e } : (e as ValidationIssue),
    );
  } else if (payload.error_message) {
    issues = [{ message: String(payload.error_message) }];
  }

  return { valid, issues, rule: payload.rule as string | undefined };
}

type Props = {
  trace: TraceResponse;
  toolCalls: ToolCall[];
};

export function ValidationResultCard({ trace, toolCalls }: Props) {
  const validationCalls = toolCalls.filter((c) => c.tool_type === "validation");

  if (validationCalls.length === 0) {
    // Fall back to the trace-level error as a loose indicator
    const traceValid = trace.status !== "failed" && !trace.error_message;
    return (
      <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
            Validation
          </h2>
        </div>
        <div className="px-4 py-4">
          <div className="flex items-center gap-2">
            <StatusBadge valid={traceValid} />
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              {traceValid ? "No validation failures detected." : "Trace ended with an error."}
            </span>
          </div>
          {trace.error_message && (
            <p className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
              {trace.error_message}
            </p>
          )}
          <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-600">
            No dedicated validation tool calls found in this trace.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Validation</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {validationCalls.length} validation span{validationCalls.length !== 1 ? "s" : ""}
        </p>
      </div>

      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {validationCalls.map((call) => {
          const parsed = parseValidationPayload(call.response_payload);
          return (
            <div key={call.id} className="px-4 py-4">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <StatusBadge valid={parsed.valid} />
                <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  {call.tool_name}
                </span>
                {parsed.rule && (
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {parsed.rule}
                  </span>
                )}
              </div>

              {parsed.issues.length > 0 && (
                <ul className="mt-1 space-y-1">
                  {parsed.issues.map((issue, idx) => (
                    <li
                      key={idx}
                      className="flex gap-2 rounded border border-red-100 bg-red-50 px-2.5 py-1.5 dark:border-red-900/50 dark:bg-red-950/30"
                    >
                      {issue.field && (
                        <span className="shrink-0 font-mono text-xs font-medium text-red-700 dark:text-red-400">
                          {issue.field}:
                        </span>
                      )}
                      <span className="text-xs text-red-700 dark:text-red-300">
                        {issue.message ?? issue.code ?? JSON.stringify(issue)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {parsed.valid && parsed.issues.length === 0 && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  All fields passed validation.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatusBadge({ valid }: { valid: boolean }) {
  return valid ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      Passed
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/40 dark:text-red-300">
      <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
      Failed
    </span>
  );
}
