"use client";

import { useState } from "react";
import type { ResponseUIValidationError } from "@/lib/types/chat";

type Props = {
  data: ResponseUIValidationError;
  onSubmit: (corrections: Record<string, unknown>) => void;
};

export function FieldCorrectionPanel({ data, onSubmit }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    data.errors.forEach((e) => {
      init[e.fieldKey] =
        e.currentValue === undefined || e.currentValue === null ? "" : String(e.currentValue);
    });
    return init;
  });

  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800/40 dark:bg-red-950/20">
      <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-800 dark:text-red-400">
        Corrections Required
      </h2>
      <p className="mb-3 text-xs text-red-600 dark:text-red-500">{data.message}</p>
      <ul className="space-y-3">
        {data.errors.map((error) => (
          <li key={error.fieldKey}>
            <label className="mb-0.5 block text-xs font-medium text-zinc-700 dark:text-zinc-300">
              {error.label}
            </label>
            <p className="mb-1 text-xs text-red-600 dark:text-red-400">{error.message}</p>
            <input
              type="text"
              value={values[error.fieldKey] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [error.fieldKey]: e.target.value }))
              }
              placeholder="Enter corrected value…"
              className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-500/20 dark:border-zinc-700 dark:bg-zinc-800"
            />
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => onSubmit(values)}
        className="mt-4 w-full rounded-md bg-blue-600 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
      >
        Submit Corrections
      </button>
    </div>
  );
}
