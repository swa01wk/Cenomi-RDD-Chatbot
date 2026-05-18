import Link from "next/link";
import { getTraceDetail } from "@/lib/api/observability-client";
import { TraceDetailHeader } from "@/components/observability/TraceDetailHeader";
import { ConversationReplay } from "@/components/observability/ConversationReplay";
import { RunTreeViewer } from "@/components/observability/RunTreeViewer";
import { StateDiffViewer } from "@/components/observability/StateDiffViewer";
import { LLMCallViewer } from "@/components/observability/LLMCallViewer";
import { ToolCallViewer } from "@/components/observability/ToolCallViewer";
import { ValidationResultCard } from "@/components/observability/ValidationResultCard";
import { FeedbackPanel } from "@/components/observability/FeedbackPanel";

type Props = { params: Promise<{ traceId: string }> };

export default async function TraceDetailPage({ params }: Props) {
  const { traceId } = await params;

  let detail;
  try {
    detail = await getTraceDetail(traceId);
  } catch {
    detail = null;
  }

  if (!detail) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-lg font-semibold text-zinc-700 dark:text-zinc-300">
          Trace not found
        </p>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Trace <span className="font-mono">{traceId}</span> does not exist or could not be
          loaded.
        </p>
        <Link
          href="/admin/agent-observability"
          className="mt-4 rounded-md border border-zinc-200 px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          ← Back to traces
        </Link>
      </div>
    );
  }

  const { trace, run_tree, state_diffs, state_snapshots, llm_calls, tool_calls, feedback } =
    detail;

  return (
    <div className="space-y-6">
      {/* Header — full-width */}
      <TraceDetailHeader trace={trace} />

      {/* Two-column grid for the detail panels */}
      <div className="grid gap-6 lg:grid-cols-2">
        <ConversationReplay trace={trace} />
        <RunTreeViewer runTree={run_tree} />
        <StateDiffViewer stateDiffs={state_diffs} stateSnapshots={state_snapshots} />
        <ValidationResultCard trace={trace} toolCalls={tool_calls} />
        <ToolCallViewer toolCalls={tool_calls} />
        <LLMCallViewer llmCalls={llm_calls} />
      </div>

      {/* Feedback — full-width at the bottom */}
      <FeedbackPanel traceId={traceId} existingFeedback={feedback} />
    </div>
  );
}
