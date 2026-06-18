"use client";

import type { UserRole } from "@/lib/types/chat";

const ROLES: {
  id: UserRole;
  label: string;
  description: string;
  icon: string;
}[] = [
  {
    id: "MALL_MANAGER",
    label: "Mall Manager",
    description: "Create handover service requests when a lease is activated",
    icon: "🏢",
  },
  {
    id: "FM_MANAGER",
    label: "FM Manager",
    description: "Conduct site inspection, upload documents, set readiness dates",
    icon: "🔧",
  },
  {
    id: "OPERATIONS",
    label: "Operations",
    description: "Conduct site inspection and approve FM review",
    icon: "⚙️",
  },
  {
    id: "DD_ENGINEER",
    label: "RDD Project Manager",
    description: "Chair handover meeting, submit report, enter contractual dates",
    icon: "📋",
  },
];

interface RoleSelectorProps {
  onSelect: (role: UserRole) => void;
}

export function RoleSelector({ onSelect }: RoleSelectorProps) {
  return (
    <div className="flex min-h-[540px] flex-col items-center justify-center px-6 py-10">
      <div className="w-full max-w-lg">
        <h2 className="mb-1 text-center text-xl font-semibold text-zinc-800 dark:text-zinc-100">
          Select your role
        </h2>
        <p className="mb-8 text-center text-sm text-zinc-500 dark:text-zinc-400">
          Choose the role that best describes your position in this workflow.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {ROLES.map((role) => (
            <button
              key={role.id}
              type="button"
              onClick={() => onSelect(role.id)}
              className="flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 text-left transition-all hover:border-blue-400 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-blue-500"
            >
              <span className="mt-0.5 text-2xl" role="img" aria-hidden>
                {role.icon}
              </span>
              <div>
                <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                  {role.label}
                </p>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                  {role.description}
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export { ROLES };
