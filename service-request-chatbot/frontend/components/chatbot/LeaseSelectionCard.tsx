"use client";

import type { ResponseUILeaseSelection } from "@/lib/types/chat";

type Props = {
  data: ResponseUILeaseSelection;
  onSelect: (leaseId: string) => void;
};

export function LeaseSelectionCard({ data, onSelect }: Props) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-800/40 dark:bg-amber-950/20">
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-400">
        Select a Lease
      </h2>
      <p className="mb-3 text-xs text-amber-700 dark:text-amber-500">{data.message}</p>
      <ul className="space-y-2">
        {data.leases.map((lease) => (
          <li key={lease.id}>
            <button
              type="button"
              onClick={() => onSelect(lease.id)}
              className="w-full rounded-md border border-zinc-200 bg-white px-3 py-2.5 text-left transition hover:border-blue-400 hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 dark:border-zinc-700 dark:bg-zinc-800 dark:hover:border-blue-500"
            >
              <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                {lease.tenantName}
              </p>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {lease.propertyName} · Unit {lease.unitNumber}
              </p>
              <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">
                {lease.leaseStartDate} → {lease.leaseEndDate}
              </p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
