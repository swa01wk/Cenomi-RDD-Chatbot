function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api`;
}

export async function uploadDocument(
  file: File,
  documentType: string,
  sessionId: string,
  srId: string,
): Promise<{ document_id: string | null; signed_url: string | null; status: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("document_type", documentType);
  form.append("session_id", sessionId);
  form.append("sr_id", srId);

  const res = await fetch(`${apiBase()}/upload`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText);
    throw new Error(`Upload failed (${res.status}): ${errText}`);
  }

  return res.json() as Promise<{ document_id: string | null; signed_url: string | null; status: string }>;
}
