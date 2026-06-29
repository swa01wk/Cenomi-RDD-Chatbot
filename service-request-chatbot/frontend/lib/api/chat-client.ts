import type { ChatServiceRequest, ChatServiceResponse, ResponseUI } from "@/lib/types/chat";
import { getStoredToken, getStoredUser } from "@/lib/api/auth-client";

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api`;
}

export async function postServiceRequestChat(
  body: ChatServiceRequest,
): Promise<ChatServiceResponse> {
  const user = getStoredUser();
  const token = getStoredToken();

  const payload: Record<string, unknown> = {
    session_id: body.sessionId ?? null,
    user_id: user?.userId ?? "demo_user",
    message: body.message,
    attachments: body.attachmentIds?.map((id) => ({ id })) ?? [],
  };

  if (body.action) payload.action = body.action;
  if (body.selectedLeaseId) payload.selected_lease_id = body.selectedLeaseId;
  if (body.correctedFields) payload.corrected_fields = body.correctedFields;
  if (body.srId) payload.sr_id = body.srId;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${apiBase()}/chat/service-request`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`Request failed (${res.status}): ${errText}`);
  }

  const data = await res.json();
  // The backend returns message text at top-level `data.message` and a
  // rendering hint at `data.ui`. Merge them so every ResponseUI variant has
  // a populated `message` field for the chat bubble.
  const responseUI = { ...data.ui, message: data.ui?.message ?? data.message } as ResponseUI;

  // `draft_preview` is an always-fresh SR snapshot included by the backend
  // whenever collected_data is non-empty and the SR is not yet submitted.
  const draftPreview = data.draft_preview
    ? ({ ...data.draft_preview, message: "" } as import("@/lib/types/chat").ResponseUISRPreviewCard)
    : undefined;

  return {
    sessionId: data.session_id,
    traceId: data.trace_id ?? undefined,
    responseUI,
    draftPreview,
  };
}
