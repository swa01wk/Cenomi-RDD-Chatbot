"use client";

import { useState, useRef } from "react";
import { uploadDocument } from "@/lib/api/upload-client";
import type { UploadedDoc } from "@/lib/types/chat";

// ─── Document type configuration ─────────────────────────────────────────────

type DocTypeConfig = {
  id: string;
  label: string;
};

const FM_DOC_TYPES: DocTypeConfig[] = [
  { id: "SR_HANDOVER_CHECKLIST", label: "Handover Checklist" },
  { id: "SR_HANDOVER_SITE_SURVEY", label: "Site Survey" },
  { id: "SR_COP_CHECKLIST_OTHER", label: "COP Checklist" },
];

const RDD_DOC_TYPES: DocTypeConfig[] = [
  { id: "DR_SR_HANDOVER_REPORT", label: "Handover Meeting Report" },
];

function getDocTypes(userRole: string | null | undefined): DocTypeConfig[] {
  if (userRole === "FM_MANAGER" || userRole === "OPERATIONS") return FM_DOC_TYPES;
  if (userRole === "DD_ENGINEER") return RDD_DOC_TYPES;
  return [];
}

function getDocLabel(docTypeId: string): string {
  return (
    [...FM_DOC_TYPES, ...RDD_DOC_TYPES].find((d) => d.id === docTypeId)?.label ?? docTypeId
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface DocumentUploadPanelProps {
  sessionId: string;
  srId: string | null;
  workflowStage: string | null | undefined;
  userRole: string | null | undefined;
  uploadedDocuments: UploadedDoc[];
  onUploadComplete: (doc: UploadedDoc) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function DocumentUploadPanel({
  sessionId,
  srId,
  workflowStage,
  userRole,
  uploadedDocuments,
  onUploadComplete,
}: DocumentUploadPanelProps) {
  const [selectedDocType, setSelectedDocType] = useState<string>("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const docTypes = getDocTypes(userRole);
  const shouldShow =
    (workflowStage === "FM_REVIEW" || workflowStage === "RDD_REVIEW") &&
    srId !== null &&
    docTypes.length > 0;

  if (!shouldShow) return null;

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !selectedDocType || !srId) return;

    setIsUploading(true);
    setUploadError(null);

    try {
      const result = await uploadDocument(file, selectedDocType, sessionId, srId);
      onUploadComplete({
        documentId: result.document_id,
        documentType: selectedDocType,
        documentTypeLabel: getDocLabel(selectedDocType),
        filename: file.name,
        signedUrl: result.signed_url,
      });
      setSelectedDocType("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed. Please try again.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        Upload Documents
      </h3>

      {/* Upload row */}
      <div className="flex flex-col gap-2 sm:flex-row">
        <select
          value={selectedDocType}
          onChange={(e) => setSelectedDocType(e.target.value)}
          disabled={isUploading}
          className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200"
        >
          <option value="">Select document type…</option>
          {docTypes.map((dt) => (
            <option key={dt.id} value={dt.id}>
              {dt.label}
            </option>
          ))}
        </select>

        <label
          className={`cursor-pointer rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
            selectedDocType && !isUploading
              ? "border-blue-600 bg-blue-600 text-white hover:bg-blue-700"
              : "cursor-not-allowed border-zinc-300 bg-zinc-100 text-zinc-400 dark:border-zinc-600 dark:bg-zinc-700 dark:text-zinc-500"
          }`}
        >
          {isUploading ? "Uploading…" : "Choose file"}
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            disabled={!selectedDocType || isUploading}
            onChange={handleFileChange}
          />
        </label>
      </div>

      {uploadError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">{uploadError}</p>
      )}

      {/* Uploaded documents list */}
      {uploadedDocuments.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {uploadedDocuments.map((doc, idx) => (
            <li
              key={doc.documentId ?? idx}
              className="flex items-center gap-2 rounded-md bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-800"
            >
              <span className="text-green-600 dark:text-green-400">✓</span>
              <span className="flex-1 truncate font-medium text-zinc-700 dark:text-zinc-200">
                {doc.filename}
              </span>
              <span className="shrink-0 text-zinc-500 dark:text-zinc-400">
                {doc.documentTypeLabel}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
