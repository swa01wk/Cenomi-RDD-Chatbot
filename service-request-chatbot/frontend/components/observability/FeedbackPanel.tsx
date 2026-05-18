"use client";

import { useState } from "react";
import { submitFeedback } from "@/lib/api/observability-client";
import type { Feedback } from "@/lib/types/observability";

type Props = {
  traceId: string;
  existingFeedback?: Feedback[];
};

const STARS = [1, 2, 3, 4, 5] as const;

export function FeedbackPanel({ traceId, existingFeedback = [] }: Props) {
  const [score, setScore] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [status, setStatus] = useState<"idle" | "submitting" | "success" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit() {
    if (score === null && !comment.trim()) return;
    setStatus("submitting");
    setErrorMsg("");
    try {
      await submitFeedback(traceId, {
        score: score ?? undefined,
        comment: comment.trim() || undefined,
        feedback_type: "rating",
      });
      setStatus("success");
      setScore(null);
      setComment("");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Submission failed");
    }
  }

  const displayStar = hover ?? score;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Feedback</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          QA / eval signal for this trace
        </p>
      </div>

      {/* Existing feedback */}
      {existingFeedback.length > 0 && (
        <div className="divide-y divide-zinc-100 border-b border-zinc-100 dark:divide-zinc-800 dark:border-zinc-800">
          {existingFeedback.map((fb) => (
            <div key={fb.id} className="px-4 py-3">
              <div className="flex items-center gap-2">
                {fb.score !== null && (
                  <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    {"★".repeat(fb.score)}{"☆".repeat(5 - fb.score)}
                  </span>
                )}
                {fb.label && (
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {fb.label}
                  </span>
                )}
                <span className="text-xs text-zinc-400">
                  {new Date(fb.created_at).toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
              {fb.comment && (
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{fb.comment}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* New feedback form */}
      <div className="px-4 py-4">
        {status === "success" ? (
          <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-2.5 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
            <span>✓</span>
            <span>Feedback submitted. Thank you.</span>
            <button
              type="button"
              onClick={() => setStatus("idle")}
              className="ml-auto text-xs underline"
            >
              Add more
            </button>
          </div>
        ) : (
          <>
            {/* Star rating */}
            <div className="mb-3">
              <p className="mb-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Score (optional)
              </p>
              <div className="flex gap-1">
                {STARS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setScore(score === s ? null : s)}
                    onMouseEnter={() => setHover(s)}
                    onMouseLeave={() => setHover(null)}
                    className={`text-2xl transition-colors ${
                      (displayStar ?? 0) >= s
                        ? "text-amber-400"
                        : "text-zinc-300 dark:text-zinc-600"
                    } hover:scale-110`}
                    aria-label={`${s} star${s !== 1 ? "s" : ""}`}
                  >
                    ★
                  </button>
                ))}
                {score !== null && (
                  <span className="ml-2 self-center text-sm text-zinc-500">
                    {score} / 5
                  </span>
                )}
              </div>
            </div>

            {/* Comment */}
            <div className="mb-3">
              <p className="mb-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Comment (optional)
              </p>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={3}
                placeholder="Note a bug, unexpected extraction, or correct behaviour…"
                className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-zinc-700 dark:text-zinc-200 dark:placeholder:text-zinc-600"
              />
            </div>

            {status === "error" && (
              <p className="mb-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
                {errorMsg}
              </p>
            )}

            <button
              type="button"
              onClick={handleSubmit}
              disabled={status === "submitting" || (score === null && !comment.trim())}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 dark:bg-blue-500 dark:hover:bg-blue-600"
            >
              {status === "submitting" ? "Submitting…" : "Submit Feedback"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
