// ─── Roles ───────────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

// ─── Domain objects ───────────────────────────────────────────────────────────

export type LeaseMatch = {
  id: string;
  tenantName: string;
  propertyName: string;
  unitNumber: string;
  leaseStartDate: string;
  leaseEndDate: string;
};

export type WorkflowStep = {
  key: string;
  label: string;
  status: "pending" | "active" | "completed" | "error";
};

export type ConfirmationField = {
  key: string;
  label: string;
  value: string | number | boolean | null;
  editable?: boolean;
};

export type FieldError = {
  fieldKey: string;
  label: string;
  message: string;
  currentValue?: unknown;
};

export type DocumentItem = {
  key: string;
  label: string;
  required: boolean;
  description?: string;
  status: "missing" | "uploaded" | "reviewing" | "accepted" | "rejected";
};

// ─── Response UI — discriminated union ───────────────────────────────────────

export type ResponseUIMessage = {
  type: "message";
  message: string;
};

export type ResponseUILeaseSelection = {
  type: "lease_selection";
  message: string;
  leases: LeaseMatch[];
};

export type ResponseUIConfirmationCard = {
  type: "confirmation_card";
  message: string;
  requestType: string;
  fields: ConfirmationField[];
};

export type ResponseUIValidationError = {
  type: "validation_error";
  message: string;
  errors: FieldError[];
};

export type ResponseUIWorkflowProgress = {
  type: "workflow_progress";
  message: string;
  steps: WorkflowStep[];
  currentStep: string;
};

export type ResponseUIDocumentRequirement = {
  type: "document_requirement";
  message: string;
  documents: DocumentItem[];
};

// A read-only field row in the SR preview card (no editable flag — always display-only).
export type PreviewField = {
  key: string;
  label: string;
  value: string | null;
};

export type ResponseUISRPreviewCard = {
  type: "sr_preview_card";
  message: string;
  requestType: string;
  /** Platform-assigned SR ID — present only when the SR has been submitted. */
  srId: string | null;
  /** Platform status string e.g. "SUBMITTED", "IN_PROCESS", "DRAFT". */
  status: string | null;
  /** True when the SR has been submitted to the platform and sr_id is a real ID. */
  isSubmitted: boolean;
  fields: PreviewField[];
};

export type ResponseUI =
  | ResponseUIMessage
  | ResponseUILeaseSelection
  | ResponseUIConfirmationCard
  | ResponseUIValidationError
  | ResponseUIWorkflowProgress
  | ResponseUIDocumentRequirement
  | ResponseUISRPreviewCard;

// ─── API contract ─────────────────────────────────────────────────────────────

export type ChatServiceRequest = {
  sessionId?: string;
  message: string;
  attachmentIds?: string[];
  selectedLeaseId?: string;
  correctedFields?: Record<string, unknown>;
  action?: "confirm" | "cancel";
  /** Platform SR ID — passed when FM/DD opens an existing SR */
  srId?: string;
};

export type ChatServiceResponse = {
  sessionId: string;
  traceId?: string;
  responseUI: ResponseUI;
  /**
   * Always-fresh draft SR snapshot emitted by the backend on every turn where
   * collected_data is non-empty and the SR has not yet been submitted.
   * Use this to keep the SR preview card in sync even when responseUI is a
   * plain message or confirmation type.
   */
  draftPreview?: ResponseUISRPreviewCard;
};

// ─── Local UI message ─────────────────────────────────────────────────────────

export type ChatMessage = {
  id: string;
  role: MessageRole;
  text: string;
  responseUI?: ResponseUI;
  traceId?: string;
  timestamp: Date;
};
