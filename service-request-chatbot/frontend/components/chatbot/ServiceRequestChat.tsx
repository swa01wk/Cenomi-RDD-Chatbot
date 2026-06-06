"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { WorkflowProgressCard } from "./WorkflowProgressCard";
import { ServiceRequestSummaryCard } from "./ServiceRequestSummaryCard";
import { FieldCorrectionPanel } from "./FieldCorrectionPanel";
import { LeaseSelectionCard } from "./LeaseSelectionCard";
import { DocumentRequirementCard } from "./DocumentRequirementCard";
import { SRPreviewCard } from "./SRPreviewCard";
import { postServiceRequestChat } from "@/lib/api/chat-client";
import type {
  ChatMessage,
  ResponseUI,
  ResponseUIConfirmationCard,
  ResponseUILeaseSelection,
  ResponseUISRPreviewCard,
  WorkflowStep,
} from "@/lib/types/chat";

// ─── Default workflow steps (shown before any API response) ──────────────────

const DEFAULT_STEPS: WorkflowStep[] = [
  { key: "understand", label: "Understand Request", status: "pending" },
  { key: "extract", label: "Extract Fields", status: "pending" },
  { key: "validate", label: "Validate", status: "pending" },
  { key: "confirm", label: "Confirm", status: "pending" },
  { key: "submit", label: "Submit", status: "pending" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildUserLabel(
  text: string,
  opts: { selectedLeaseId?: string; latestUI?: ResponseUI | null },
): string {
  if (opts.selectedLeaseId && opts.latestUI?.type === "lease_selection") {
    const lease = (opts.latestUI as ResponseUILeaseSelection).leases.find(
      (l) => l.id === opts.selectedLeaseId,
    );
    return lease
      ? `Selected: ${lease.tenantName} – ${lease.propertyName}, Unit ${lease.unitNumber}`
      : `Selected lease: ${opts.selectedLeaseId}`;
  }
  return text;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ServiceRequestChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isPending, setIsPending] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [latestUI, setLatestUI] = useState<ResponseUI | null>(null);
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>(DEFAULT_STEPS);
  // Persists the most recent SR draft preview across all turns, regardless of
  // what responseUI type the current turn returned.  Updated from draftPreview
  // (authoritative backend snapshot) or from responseUI when it is sr_preview_card.
  const [latestSRPreview, setLatestSRPreview] = useState<ResponseUISRPreviewCard | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isPending]);

  // ── Core turn function ─────────────────────────────────────────────────────

  const sendTurn = useCallback(
    async (
      userVisibleText: string,
      opts: {
        attachments?: File[];
        selectedLeaseId?: string;
        correctedFields?: Record<string, unknown>;
        action?: "confirm" | "cancel";
        apiMessage?: string;
      } = {},
    ) => {
      if (userVisibleText) {
        const userMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "user",
          text: userVisibleText,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, userMsg]);
      }

      setIsPending(true);

      try {
        const res = await postServiceRequestChat({
          sessionId,
          message: opts.apiMessage ?? userVisibleText,
          attachmentIds: opts.attachments?.map((f) => f.name),
          selectedLeaseId: opts.selectedLeaseId,
          correctedFields: opts.correctedFields,
          action: opts.action,
        });

        setSessionId(res.sessionId);

        if (res.responseUI.type === "workflow_progress") {
          setWorkflowSteps(res.responseUI.steps);
        }

        setLatestUI(res.responseUI);

        // Keep the SR preview in sync on every turn.
        // draftPreview is an authoritative snapshot from the backend; fall back
        // to responseUI itself when the turn directly returned a preview card.
        if (res.draftPreview) {
          setLatestSRPreview(res.draftPreview);
        } else if (res.responseUI.type === "sr_preview_card") {
          setLatestSRPreview(res.responseUI as ResponseUISRPreviewCard);
        }

        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          text: res.responseUI.message,
          responseUI: res.responseUI,
          traceId: res.traceId,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const errorMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          text: err instanceof Error ? err.message : "An unexpected error occurred.",
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsPending(false);
      }
    },
    [sessionId],
  );

  // ── Interaction handlers ───────────────────────────────────────────────────

  const handleSend = useCallback(
    (text: string, attachments: File[]) => {
      sendTurn(text, { attachments });
    },
    [sendTurn],
  );

  const handleLeaseSelect = useCallback(
    (leaseId: string) => {
      const label = buildUserLabel("", { selectedLeaseId: leaseId, latestUI });
      sendTurn(label, { selectedLeaseId: leaseId, apiMessage: "" });
    },
    [latestUI, sendTurn],
  );

  const handleConfirm = useCallback(
    (fields: Record<string, unknown>) => {
      sendTurn("Confirmed. Please submit.", {
        correctedFields: fields,
        action: "confirm",
      });
    },
    [sendTurn],
  );

  const handleCancel = useCallback(() => {
    sendTurn("Let me make some changes.", { action: "cancel" });
  }, [sendTurn]);

  const handleCorrections = useCallback(
    (corrections: Record<string, unknown>) => {
      sendTurn("Here are my corrections.", { correctedFields: corrections });
    },
    [sendTurn],
  );

  // ── Sidebar card selection ─────────────────────────────────────────────────

  const sidebarUI = latestUI;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* ── Chat panel ──────────────────────────────────────────────────── */}
      <section className="flex min-h-[540px] flex-col rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900 lg:col-span-2">
        {/* Panel header */}
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Service Request Assistant
          </span>
          {/* Debug mode toggle */}
          <label className="flex cursor-pointer select-none items-center gap-1.5 text-xs text-zinc-400">
            <span>Debug</span>
            <button
              type="button"
              role="switch"
              aria-checked={debugMode}
              onClick={() => setDebugMode((d) => !d)}
              className={`relative h-4 w-7 rounded-full transition-colors ${
                debugMode ? "bg-blue-600" : "bg-zinc-300 dark:bg-zinc-700"
              }`}
            >
              <span
                className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${
                  debugMode ? "left-3.5" : "left-0.5"
                }`}
              />
            </button>
          </label>
        </div>

        {/* Messages area */}
        <div
          ref={scrollRef}
          className="flex-1 space-y-3 overflow-y-auto p-4"
          style={{ maxHeight: "420px" }}
        >
          {messages.length === 0 && !isPending ? (
            <div className="flex h-full min-h-[200px] items-center justify-center">
              <p className="text-sm text-zinc-400 dark:text-zinc-600">
                Describe your service request to get started.
              </p>
            </div>
          ) : (
            <>
              {messages.map((m, idx) => {
                const isLastMsg = idx === messages.length - 1;
                const isConfirmCard = m.role === "assistant" && m.responseUI?.type === "confirmation_card";
                const isPreviewCard = m.role === "assistant" && m.responseUI?.type === "sr_preview_card";
                return (
                  <div key={m.id}>
                    <MessageBubble
                      role={m.role}
                      text={m.text}
                      traceId={m.traceId}
                      showTrace={debugMode}
                    />
                    {isConfirmCard && (
                      <div className="mt-2">
                        <ServiceRequestSummaryCard
                          data={m.responseUI as ResponseUIConfirmationCard}
                          onConfirm={handleConfirm}
                          onCancel={handleCancel}
                          readOnly={!isLastMsg}
                        />
                      </div>
                    )}
                    {isPreviewCard && (
                      <div className="mt-2">
                        {/* Use latestSRPreview so the card reflects field updates
                            made in subsequent turns; only the last card is editable
                            and only when the SR has not yet been submitted. */}
                        <SRPreviewCard
                          data={latestSRPreview ?? (m.responseUI as ResponseUISRPreviewCard)}
                          onSave={
                            isLastMsg && !(latestSRPreview?.isSubmitted)
                              ? handleCorrections
                              : undefined
                          }
                        />
                      </div>
                    )}
                  </div>
                );
              })}
              {isPending && <MessageBubble role="assistant" text="" isLoading />}
            </>
          )}
        </div>

        {/* Input */}
        <ChatInput onSend={handleSend} disabled={isPending} />
      </section>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="space-y-3">
        <WorkflowProgressCard steps={workflowSteps} />

        {sidebarUI?.type === "lease_selection" && (
          <LeaseSelectionCard data={sidebarUI} onSelect={handleLeaseSelect} />
        )}

        {sidebarUI?.type === "confirmation_card" && (
          <ServiceRequestSummaryCard
            data={sidebarUI}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
          />
        )}

        {sidebarUI?.type === "validation_error" && (
          <FieldCorrectionPanel data={sidebarUI} onSubmit={handleCorrections} />
        )}

        {sidebarUI?.type === "document_requirement" && (
          <DocumentRequirementCard data={sidebarUI} />
        )}

        {/* Always render the latest SR draft/submitted preview when available.
            latestSRPreview persists across turns so the card stays visible
            even when the current responseUI is a plain message type.
            onSave is only wired for drafts; submitted SRs are read-only. */}
        {latestSRPreview && (
          <SRPreviewCard
            data={latestSRPreview}
            onSave={latestSRPreview.isSubmitted ? undefined : handleCorrections}
          />
        )}

        {/* Session debug panel */}
        {debugMode && sessionId && (
          <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              Session ID
            </p>
            <p className="mt-1 break-all font-mono text-[10px] text-zinc-400 dark:text-zinc-600">
              {sessionId}
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
