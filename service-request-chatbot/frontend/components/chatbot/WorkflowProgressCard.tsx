import type { WorkflowStep } from "@/lib/types/chat";

type Props = {
  steps?: WorkflowStep[];
};

const DEFAULT_STEPS: WorkflowStep[] = [
  { key: "understand", label: "Understand Request", status: "pending" },
  { key: "extract", label: "Extract Fields", status: "pending" },
  { key: "validate", label: "Validate", status: "pending" },
  { key: "confirm", label: "Confirm", status: "pending" },
  { key: "submit", label: "Submit", status: "pending" },
];

function StepIcon({ status }: { status: WorkflowStep["status"] }) {
  if (status === "completed") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/40">
        <svg
          className="h-3 w-3 text-emerald-600 dark:text-emerald-400"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="2 6 5 9 10 3" />
        </svg>
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/40">
        <span className="h-2 w-2 animate-pulse rounded-full bg-blue-600 dark:bg-blue-400" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/40">
        <svg
          className="h-3 w-3 text-red-600 dark:text-red-400"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        >
          <line x1="2" y1="2" x2="10" y2="10" />
          <line x1="10" y1="2" x2="2" y2="10" />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 border-zinc-200 dark:border-zinc-700" />
  );
}

export function WorkflowProgressCard({ steps = DEFAULT_STEPS }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Workflow
      </h2>
      <ol className="space-y-2.5">
        {steps.map((step) => (
          <li key={step.key} className="flex items-center gap-2.5">
            <StepIcon status={step.status} />
            <span
              className={`text-sm ${
                step.status === "active"
                  ? "font-semibold text-blue-600 dark:text-blue-400"
                  : step.status === "completed"
                    ? "text-zinc-400 line-through dark:text-zinc-600"
                    : step.status === "error"
                      ? "text-red-600 dark:text-red-400"
                      : "text-zinc-500 dark:text-zinc-400"
              }`}
            >
              {step.label}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
