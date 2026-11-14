import { ThreadHistoryStatus } from "@/components/thread/ThreadHistoryStatus";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import type { UIMessage } from "@/lib/types";

export function SubagentThreadView({ messages, loading, error, isStreaming, activeTurnId, runStartedAt, onRetry }: {
  messages: UIMessage[];
  loading: boolean;
  error: string | null;
  isStreaming: boolean;
  activeTurnId?: string | null;
  runStartedAt: number;
  onRetry: () => void;
}) {
  return <>
    {loading || error ? <ThreadHistoryStatus className="relative" loading={loading} error={error} onRetry={onRetry} /> : null}
    <ThreadMessages messages={messages} isStreaming={isStreaming} activeTurnId={activeTurnId} runStartedAt={runStartedAt} />
  </>;
}
