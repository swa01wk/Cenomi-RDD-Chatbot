import type { DocumentItem, ResponseUIDocumentRequirement } from "@/lib/types/chat";

type Props = {
  data: ResponseUIDocumentRequirement;
};

const STATUS_CONFIG: Record<DocumentItem["status"], { label: string; className: string }> = {
  missing: {
    label: "Missing",
    className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  },
  uploaded: {
    label: "Uploaded",
    className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  },
  reviewing: {
    label: "Reviewing",
    className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
  },
  accepted: {
    label: "Accepted",
    className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  },
  rejected: {
    label: "Rejected",
    className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  },
};

export function DocumentRequirementCard({ data }: Props) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Required Documents
      </h2>
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{data.message}</p>
      <ul className="space-y-2.5">
        {data.documents.map((doc) => {
          const cfg = STATUS_CONFIG[doc.status];
          return (
            <li key={doc.key} className="flex items-start gap-2.5">
              <span
                className={`mt-0.5 shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${cfg.className}`}
              >
                {cfg.label}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                  {doc.label}
                  {doc.required && <span className="ml-1 text-red-500">*</span>}
                </p>
                {doc.description && (
                  <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                    {doc.description}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
