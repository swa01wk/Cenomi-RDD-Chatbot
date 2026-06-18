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
import { StageActions } from "./StageActions";
import { DocumentUploadPanel } from "./DocumentUploadPanel";
import { LifecycleStepper } from "./LifecycleStepper";
import { StageContextPanel } from "./StageContextPanel";
import { ROLES } from "./RoleSelector";
import { postServiceRequestChat } from "@/lib/api/chat-client";
import type {
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

function getRoleLabel(roleId: string): string {
  return ROLES.find((r) => r.id === roleId)?.label ?? roleId;
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface ServiceRequestChatProps {
  userRole: string;
  onClearRole: () => void;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ServiceRequestChat({ userRole, onClearRole }: ServiceRequestChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isPending, setIsPending] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [latestUI, setLatestUI] = useState<ResponseUI | null>(null);
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>(DEFAULT_STEPS);
  const [latestSRPreview, setLatestSRPreview] = useState<ResponseUISRPreviewCard | null>(null);

  // Stage-aware state
  const [workflowStage, setWorkflowStage] = useState<string | null>(null);
  const [rddStatus, setRddStatus] = useState<string | null>(null);
  const [collectedData, setCollectedData] = useState<Record<string, string> | null>(null);
  const [srId, setSrId] = useState<string | null>(null);
  const [uploadedDocuments, setUploadedDocuments] = useState<UploadedDoc[]>([]);

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
        action?: string;
        apiMessage?: string;
        suppressUserBubble?: boolean;
      } = {},
    ) => {
      if (userVisibleText && !opts.suppressUserBubble) {
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
          userRole,
        });

        setSessionId(res.sessionId);

        if (res.responseUI.type === "workflow_progress") {
          setWorkflowSteps(res.responseUI.steps);
        }

        setLatestUI(res.responseUI);

        // Update stage-aware state from API response
        if (res.workflowStage !== undefined) setWorkflowStage(res.workflowStage);
        if (res.rddStatus !== undefined) setRddStatus(res.rddStatus);
        if (res.collectedData !== undefined) setCollectedData(res.collectedData);
        if (res.srId !== undefined) setSrId(res.srId);

        // Keep the SR preview in sync
        if (res.draftPreview) {
          setLatestSRPreview(res.draftPreview);
          // Sync srId from draft preview as a fallback
          if (res.draftPreview.srId && !srId) {
            setSrId(res.draftPreview.srId);
          }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, userRole],
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

  // Stage action buttons (FM approve, RDD submit/final approve, etc.)
  const handleStageAction = useCallback(
    (action: string) => {
      // Don't show a user chat bubble for pure button actions
      sendTurn("", {
        action,
        apiMessage: "",
        suppressUserBubble: true,
      });
    },
    [sendTurn],
  );

  // Document upload complete callback
  const handleUploadComplete = useCallback((doc: UploadedDoc) => {
    setUploadedDocuments((prev) => [...prev, doc]);
  }, []);

  // ── Sidebar card selection ─────────────────────────────────────────────────

  const sidebarUI = latestUI;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {/* ── Chat panel ──────────────────────────────────────────────────── */}
      <section className="flex min-h-[540px] flex-col rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900 lg:col-span-2">
        {/* Panel header */}
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              Service Request Assistant
            </span>
            {/* Role badge */}
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
              {getRoleLabel(userRole)}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Switch role button */}
            <button
              type="button"
              onClick={onClearRole}
              className="text-xs text-zinc-400 underline hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300"
            >
              Switch role
            </button>

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
        </div>

        {/* Stage context panel (FM/RDD reviewers see prior-stage data) */}
        {(workflowStage === "FM_REVIEW" || workflowStage === "RDD_REVIEW") && srId && (
          <div className="border-b border-zinc-100 px-4 py-2 dark:border-zinc-800">
            <StageContextPanel
              workflowStage={workflowStage}
              collectedData={collectedData}
              srId={srId}
            />
          </div>
        )}

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

        {/* Stage action buttons (FM approve / RDD submit / final approve) */}
        <StageActions
          workflowStage={workflowStage}
          userRole={userRole}
          rddStatus={rddStatus}
          onAction={handleStageAction}
          disabled={isPending}
        />

        {/* Input */}
        <ChatInput onSend={handleSend} disabled={isPending} />
      </section>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="space-y-3">
        {/* Lifecycle stepper — shown once SR is created */}
        <LifecycleStepper currentStage={workflowStage} srId={srId} />

        <WorkflowProgressCard steps={workflowSteps} />

        {/* Document upload panel for FM / RDD stages */}
        {sessionId && (
          <DocumentUploadPanel
            sessionId={sessionId}
            srId={srId}
            workflowStage={workflowStage}
            userRole={userRole}
            uploadedDocuments={uploadedDocuments}
            onUploadComplete={handleUploadComplete}
          />
        )}

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

        {/* Always render the latest SR draft/submitted preview when available */}
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
