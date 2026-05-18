import type { TraceResponse } from "@/lib/types/observability";

type Props = { trace: TraceResponse };

export function ConversationReplay({ trace }: Props) {
  const hasInput = !!trace.input_message;
  const hasOutput = !!trace.output_message;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
          Conversation
        </h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Auditable input/output for this trace turn
        </p>
      </div>

      <div className="space-y-3 p-4">
        {/* User input — right-aligned */}
        {hasInput && (
          <div className="flex justify-end">
            <div className="max-w-[85%]">
              <p className="mb-1 text-right text-xs font-medium text-zinc-500 dark:text-zinc-400">
                User
              </p>
              <div className="rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2.5 text-sm text-white shadow-sm">
                {trace.input_message}
              </div>
            </div>
          </div>
        )}

        {/* Agent output — left-aligned */}
        {hasOutput && (
          <div className="flex justify-start">
            <div className="max-w-[85%]">
              <p className="mb-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
                Agent
              </p>
              <div className="rounded-2xl rounded-tl-sm border border-zinc-200 bg-zinc-50 px-4 py-2.5 text-sm text-zinc-800 shadow-sm dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
                {trace.output_message}
              </div>
            </div>
          </div>
        )}

        {!hasInput && !hasOutput && (
          <p className="py-4 text-center text-sm text-zinc-400 dark:text-zinc-600">
            No messages recorded for this trace.
          </p>
        )}
      </div>

      {/* Agent decision summary */}
      <div className="border-t border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Agent Decision
        </p>
        <div className="flex flex-wrap gap-3 text-sm">
          <DecisionField label="Intent" value={trace.intent} />
          <DecisionField label="Active Agent" value={trace.active_agent} mono />
          <DecisionField label="Stage Transition">
            {(trace.workflow_stage_before || trace.workflow_stage_after) ? (
              <span className="font-mono text-xs">
                {trace.workflow_stage_before ?? "—"}
                {" → "}
                {trace.workflow_stage_after ?? "—"}
              </span>
            ) : undefined}
          </DecisionField>
          <DecisionField label="Service" value={trace.service_category} />
          <DecisionField label="Sub-category" value={trace.sub_category} />
        </div>
      </div>
    </div>
  );
}

function DecisionField({
  label,
  value,
  mono,
  children,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  children?: React.ReactNode;
}) {
  const display = children ?? (
    value ? (
      <span className={mono ? "font-mono text-xs" : "text-xs"}>{value}</span>
    ) : (
      <span className="text-xs text-zinc-400 dark:text-zinc-600">—</span>
    )
  );
  return (
    <div className="rounded border border-zinc-100 bg-zinc-50 px-2.5 py-1.5 dark:border-zinc-700 dark:bg-zinc-800">
      <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </p>
      <div className="mt-0.5 text-zinc-700 dark:text-zinc-300">{display}</div>
    </div>
  );
}
