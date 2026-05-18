type Props = {
  role: "user" | "assistant";
  text: string;
  traceId?: string;
  showTrace?: boolean;
  isLoading?: boolean;
};

export function MessageBubble({ role, text, traceId, showTrace, isLoading }: Props) {
  const isUser = role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="flex max-w-[82%] flex-col gap-1">
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "bg-blue-600 text-white"
              : "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
          }`}
        >
          {isLoading ? (
            <span className="flex items-center gap-1 py-0.5">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 [animation-delay:300ms]" />
            </span>
          ) : (
            <span className="whitespace-pre-wrap">{text}</span>
          )}
        </div>
        {showTrace && traceId && (
          <span className="px-1 font-mono text-[10px] text-zinc-400 dark:text-zinc-600">
            trace: {traceId}
          </span>
        )}
      </div>
    </div>
  );
}
