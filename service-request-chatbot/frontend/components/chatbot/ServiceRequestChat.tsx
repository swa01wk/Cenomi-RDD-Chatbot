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
import { LifecycleStepper } from "./LifecycleStepper";
import { StageActions } from "./StageActions";
import { StageContextPanel } from "./StageContextPanel";
import { DocumentUploadPanel } from "./DocumentUploadPanel";
import { postServiceRequestChat } from "@/lib/api/chat-client";
import { getStoredUser } from "@/lib/api/auth-client";
import type {
  ChatAction,
  ChatMessage,
  ResponseUI,
  ResponseUIConfirmationCard,
  ResponseUILeaseSelection,
  ResponseUISRPreviewCard,
  UploadedDoc,
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

const ACTION_LABELS: Record<string, string> = {
  save_fm_progress: "Saving FM progress…",
  approve_fm_review: "Approving FM review…",
  reject_fm_review: "Rejecting FM review…",
  submit_rdd_report: "Submitting RDD report…",
  approve_rdd_final: "Final approval…",
};

// ─── Component ───────────────────────────────────────────────────────────────

export function ServiceRequestChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isPending, setIsPending] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [latestUI, setLatestUI] = useState<ResponseUI | null>(null);
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>(DEFAULT_STEPS);
  const [latestSRPreview, setLatestSRPreview] = useState<ResponseUISRPreviewCard | null>(null);

  // Lifecycle state — populated from response.state on every turn
  const [workflowStage, setWorkflowStage] = useState<string | null>(null);
  const [srId, setSrId] = useState<string | null>(null);
  const [uploadedDocuments, setUploadedDocuments] = useState<UploadedDoc[]>([]);
  const [rddStatus, setRddStatus] = useState<string | null>(null);

  // "Open existing SR" input — FM/DD can type an SR ID to continue a lifecycle
  const [openSrInput, setOpenSrInput] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);

  // Get role from stored JWT user
  const userRole = getStoredUser()?.role ?? null;

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
        action?: ChatAction;
        apiMessage?: string;
        srIdOverride?: string;
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
          srId: opts.srIdOverride ?? srId ?? undefined,
        });

        setSessionId(res.sessionId);

        if (res.responseUI.type === "workflow_progress") {
          setWorkflowSteps(res.responseUI.steps);
        }

        setLatestUI(res.responseUI);

        // Update lifecycle state from response.state
        if (res.workflowStage !== undefined) setWorkflowStage(res.workflowStage);
        if (res.srId) setSrId(res.srId);

        // Track rdd_status from backend_refs if present in preview data
        const previewData = res.draftPreview ?? (res.responseUI.type === "sr_preview_card" ? res.responseUI : null);
        if (previewData?.status) {
          setRddStatus(previewData.status);
        }

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
    [sessionId, srId],
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

  // Handles FM/RDD structured lifecycle actions from StageActions buttons
  const handleStageAction = useCallback(
    (action: string) => {
      const label = ACTION_LABELS[action] ?? action;
      sendTurn(label, { action: action as ChatAction, apiMessage: "" });
    },
    [sendTurn],
  );

  // Handles a successfully uploaded document — adds to local list and notifies backend
  const handleUploadComplete = useCallback((doc: UploadedDoc) => {
    setUploadedDocuments((prev) => [...prev, doc]);
  }, []);

  // Opens an existing SR by SR ID (for FM Manager / DD Engineer)
  const handleOpenSR = useCallback(() => {
    const trimmed = openSrInput.trim();
    if (!trimmed) return;
    setSrId(trimmed);
    sendTurn(`Opening SR ${trimmed}`, {
      apiMessage: `I want to continue working on service request ${trimmed}`,
      srIdOverride: trimmed,
    });
    setOpenSrInput("");
  }, [openSrInput, sendTurn]);

  // ── Sidebar card selection ─────────────────────────────────────────────────

  const sidebarUI = latestUI;
  const isLifecycleStage = workflowStage === "FM_REVIEW" || workflowStage === "RDD_REVIEW";

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* ── Chat panel ──────────────────────────────────────────────────── */}
      <section className="flex min-h-[540px] flex-col rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900 lg:col-span-2">
        {/* Panel header */}
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Service Request Assistant
          </span>
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

        {/* FM/RDD stage action buttons — shown inline above chat input */}
        <StageActions
          workflowStage={workflowStage}
          userRole={userRole}
          rddStatus={rddStatus}
          onAction={handleStageAction}
          disabled={isPending}
        />

        {/* Chat input */}
        <ChatInput onSend={handleSend} disabled={isPending} />
      </section>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="space-y-3">
        {/* Lifecycle stepper — shown once an SR exists */}
        <LifecycleStepper currentStage={workflowStage} srId={srId} />

        {/* Open existing SR panel — for FM Manager / DD Engineer */}
        {!srId && (
          <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-700 dark:bg-zinc-900">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              Continue Existing SR
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Enter SR ID…"
                value={openSrInput}
                onChange={(e) => setOpenSrInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleOpenSR()}
                className="flex-1 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-xs text-zinc-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200"
              />
              <button
                type="button"
                onClick={handleOpenSR}
                disabled={!openSrInput.trim() || isPending}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Open
              </button>
            </div>
          </div>
        )}

        {/* SR context panel — shown during FM/RDD review */}
        <StageContextPanel
          workflowStage={workflowStage}
          collectedData={latestSRPreview?.fields?.reduce(
            (acc, f) => ({ ...acc, [f.key]: f.value ?? "" }),
            {} as Record<string, string>,
          )}
          srId={srId}
        />

        {/* Document upload panel — stage-gated, shown during FM/RDD review */}
        {isLifecycleStage && srId && sessionId && (
          <DocumentUploadPanel
            sessionId={sessionId}
            srId={srId}
            workflowStage={workflowStage}
            userRole={userRole}
            uploadedDocuments={uploadedDocuments}
            onUploadComplete={handleUploadComplete}
          />
        )}

        {/* CREATE_SR workflow progress steps */}
        {!isLifecycleStage && <WorkflowProgressCard steps={workflowSteps} />}

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

        {/* Always render latest SR draft/submitted preview */}
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
            {workflowStage && (
              <>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                  Stage
                </p>
                <p className="mt-1 font-mono text-[10px] text-zinc-400 dark:text-zinc-600">
                  {workflowStage}
                </p>
              </>
            )}
            {srId && (
              <>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                  SR ID
                </p>
                <p className="mt-1 break-all font-mono text-[10px] text-zinc-400 dark:text-zinc-600">
                  {srId}
                </p>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
