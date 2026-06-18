"use client";

type StageConfig = {
  id: string;
  label: string;
  role: string;
};

const STAGES: StageConfig[] = [
  { id: "CREATE_SR", label: "Create SR", role: "Mall Manager" },
  { id: "FM_REVIEW", label: "FM Review", role: "FM Manager" },
  { id: "RDD_REVIEW", label: "RDD Review", role: "RDD PM" },
  { id: "SR_COMPLETED", label: "Complete", role: "" },
];

function getStageIndex(stage: string | null | undefined): number {
  if (!stage) return 0;
  const idx = STAGES.findIndex((s) => s.id === stage);
  return idx >= 0 ? idx : 0;
}

interface LifecycleStepperProps {
  currentStage: string | null | undefined;
  srId: string | null | undefined;
}

export function LifecycleStepper({ currentStage, srId }: LifecycleStepperProps) {
  if (!srId) return null;

  const currentIdx = getStageIndex(currentStage);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-700 dark:bg-zinc-900">
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        Lifecycle Progress
      </p>

      <div className="flex items-center gap-0">
        {STAGES.map((stage, idx) => {
          const isPast = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const isFuture = idx > currentIdx;
          const isLast = idx === STAGES.length - 1;

          return (
            <div key={stage.id} className="flex flex-1 items-center">
              {/* Step */}
              <div className="flex flex-col items-center">
                <div
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold transition-colors ${
                    isPast
                      ? "bg-green-500 text-white"
                      : isCurrent
                        ? "bg-blue-600 text-white ring-2 ring-blue-300 dark:ring-blue-700"
                        : "bg-zinc-200 text-zinc-400 dark:bg-zinc-700 dark:text-zinc-500"
                  }`}
                >
                  {isPast ? "✓" : idx + 1}
                </div>
                <div className="mt-1 flex flex-col items-center">
                  <span
                    className={`text-center text-[10px] font-medium leading-tight ${
                      isCurrent
                        ? "text-blue-600 dark:text-blue-400"
                        : isPast
                          ? "text-green-600 dark:text-green-400"
                          : "text-zinc-400 dark:text-zinc-500"
                    } ${isCurrent ? "font-bold" : ""}`}
                  >
                    {stage.label}
                  </span>
                  {stage.role && (
                    <span className="text-center text-[9px] text-zinc-400 dark:text-zinc-500">
                      {stage.role}
                    </span>
                  )}
                </div>
              </div>

              {/* Connector line */}
              {!isLast && (
                <div
                  className={`h-0.5 flex-1 ${
                    idx < currentIdx
                      ? "bg-green-400 dark:bg-green-600"
                      : "bg-zinc-200 dark:bg-zinc-700"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
