import { getStoredToken } from "@/lib/api/auth-client";

// ─── Response shape from POST /api/upload ─────────────────────────────────────

export type DocumentUploadResponse = {
  filename: string;
  content_type: string;
  document_type: string;
  document_id: string | null;
  signed_url: string | null;
  file_path: string | null;
  status: "uploaded" | string;
};

// ─── API base ─────────────────────────────────────────────────────────────────

function apiBase(): string {
  // Backend mounts upload at /api/upload — not /api/v1/upload.
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api`;
}

// ─── Upload function ──────────────────────────────────────────────────────────

/**
 * Upload a service request document to the platform via the backend.
 *
 * @param file           The file to upload (PDF, JPEG, or PNG).
 * @param documentType   Document type identifier (e.g. "SR_HANDOVER_CHECKLIST").
 * @param sessionId      Chat session UUID — used to resolve backend refs (sr_id, lease_id).
 * @param srId           Explicit SR ID override (optional; overrides draft-derived sr_id).
 */
export async function uploadDocument(
  file: File,
  documentType: string,
  sessionId: string,
  srId?: string | null,
): Promise<DocumentUploadResponse> {
  const token = getStoredToken();

  const form = new FormData();
  form.append("file", file);
  form.append("document_type", documentType);
  form.append("session_id", sessionId);
  if (srId) form.append("sr_id", srId);

  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${apiBase()}/upload`, {
    method: "POST",
    headers,
    body: form,
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`Upload failed (${res.status}): ${errText}`);
  }

  return (await res.json()) as DocumentUploadResponse;
}
