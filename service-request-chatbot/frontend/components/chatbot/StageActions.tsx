"use client";

interface StageActionsProps {
  workflowStage: string | null | undefined;
  userRole: string | null | undefined;
  rddStatus?: string | null;
  onAction: (action: string) => void;
  disabled?: boolean;
}

type ActionButton = {
  label: string;
  action: string;
  variant: "primary" | "secondary" | "success";
};

function getButtons(
  userRole: string | null | undefined,
  workflowStage: string | null | undefined,
  rddStatus: string | null | undefined,
): ActionButton[] {
  if (!workflowStage || !userRole) return [];

  if (
    (userRole === "FM_MANAGER" || userRole === "OPERATIONS") &&
    workflowStage === "FM_REVIEW"
  ) {
    return [
      { label: "Save Progress", action: "save_fm_progress", variant: "secondary" },
      { label: "Approve Review", action: "approve_fm_review", variant: "success" },
    ];
  }

  if (userRole === "DD_ENGINEER" && workflowStage === "RDD_REVIEW") {
    if (rddStatus === "REPORT_SUBMITTED") {
      return [{ label: "Final Approve", action: "approve_rdd_final", variant: "success" }];
    }
    return [{ label: "Submit Report", action: "submit_rdd_report", variant: "primary" }];
  }

  return [];
}

const VARIANT_CLASSES: Record<ActionButton["variant"], string> = {
  primary:
    "bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-500",
  secondary:
    "border border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 focus-visible:ring-zinc-400 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700",
  success:
    "bg-green-600 text-white hover:bg-green-700 focus-visible:ring-green-500",
};

export function StageActions({
  workflowStage,
  userRole,
  rddStatus,
  onAction,
  disabled = false,
}: StageActionsProps) {
  const buttons = getButtons(userRole, workflowStage, rddStatus);

  if (buttons.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 border-t border-zinc-100 px-4 py-2 dark:border-zinc-800">
      {buttons.map((btn) => (
        <button
          key={btn.action}
          type="button"
          disabled={disabled}
          onClick={() => onAction(btn.action)}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[btn.variant]}`}
        >
          {btn.label}
        </button>
      ))}
    </div>
  );
}
