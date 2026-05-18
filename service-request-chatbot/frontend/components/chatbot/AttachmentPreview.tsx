type Props = {
  file: File;
  onRemove: () => void;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AttachmentPreview({ file, onRemove }: Props) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-800">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="h-3 w-3 shrink-0 text-zinc-400"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <polyline points="13 2 13 9 20 9" />
      </svg>
      <span className="max-w-[120px] truncate text-zinc-700 dark:text-zinc-300">{file.name}</span>
      <span className="text-zinc-400">{formatSize(file.size)}</span>
      <button
        type="button"
        onClick={onRemove}
        className="ml-0.5 leading-none text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
        aria-label={`Remove ${file.name}`}
      >
        ×
      </button>
    </div>
  );
}
