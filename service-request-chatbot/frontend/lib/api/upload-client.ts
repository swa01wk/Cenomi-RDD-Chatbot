function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const prefix = process.env.NEXT_PUBLIC_API_V1_PREFIX ?? "/api/v1";
  return `${base.replace(/\/$/, "")}${prefix}`;
}

export async function uploadDocument(file: File): Promise<{ filename: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBase()}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`upload failed: ${res.status}`);
  }
  return (await res.json()) as { filename: string; status: string };
}
