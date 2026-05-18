export type ValidationIssue = {
  code: string;
  message: string;
  fieldKey?: string;
};

export type ServiceRequestDraft = {
  id: string;
  sessionId: string;
  payload: Record<string, unknown>;
};
