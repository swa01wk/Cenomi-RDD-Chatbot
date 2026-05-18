import type { ChatServiceRequest, ChatServiceResponse, ResponseUI } from "@/lib/types/chat";

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api`;
}

export async function postServiceRequestChat(
  body: ChatServiceRequest,
): Promise<ChatServiceResponse> {
  const payload: Record<string, unknown> = {
    session_id: body.sessionId ?? null,
    user_id: "demo_user",
    message: body.message,
    attachments: body.attachmentIds?.map((id) => ({ id })) ?? [],
  };

  if (body.action) payload.action = body.action;
  if (body.selectedLeaseId) payload.selected_lease_id = body.selectedLeaseId;
  if (body.correctedFields) payload.corrected_fields = body.correctedFields;

  const res = await fetch(`${apiBase()}/chat/service-request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  return {
    sessionId: data.session_id,
    traceId: data.trace_id ?? undefined,
    responseUI,
  };
}
