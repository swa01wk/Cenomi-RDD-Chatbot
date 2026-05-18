"use client";

import { useState, useCallback } from "react";
import { FileUploadButton } from "./FileUploadButton";
import { AttachmentPreview } from "./AttachmentPreview";

type Props = {
  onSend: (text: string, attachments: File[]) => void;
  disabled?: boolean;
};

export function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);

  const handleSend = useCallback(() => {
    const text = value.trim();
    if (!text && attachments.length === 0) return;
    onSend(text, attachments);
    setValue("");
    setAttachments([]);
  }, [value, attachments, onSend]);

  const handleFilesAdded = useCallback((files: File[]) => {
    setAttachments((prev) => [...prev, ...files]);
  }, []);

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const canSend = !disabled && (value.trim().length > 0 || attachments.length > 0);

  return (
    <div className="border-t border-zinc-100 dark:border-zinc-800">
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-2.5">
          {attachments.map((file, i) => (
            <AttachmentPreview
              key={`${file.name}-${i}`}
              file={file}
              onRemove={() => removeAttachment(i)}
            />
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 p-3">
        <FileUploadButton disabled={disabled} onFiles={handleFilesAdded} />
        <textarea
          className="max-h-[120px] min-h-[44px] flex-1 resize-none rounded-md border border-zinc-300 bg-transparent px-3 py-2.5 text-sm leading-snug outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:focus:border-blue-500"
          placeholder="Describe your service request…"
          value={value}
          disabled={disabled}
          rows={1}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) handleSend();
            }
          }}
        />
        <button
          type="button"
          className="flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-3.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canSend}
          onClick={handleSend}
        >
          Send
        </button>
      </div>
    </div>
  );
}
