import { SubagentThreadView } from "@/components/thread/SubagentThreadView";
import { useSubagentThread } from "@/components/thread/useSubagentThread";
import type { SubagentTaskSnapshot } from "@/lib/types";

interface SubagentThreadProps {
  token: string;
  sessionKey: string;
  task: SubagentTaskSnapshot;
  historyEnabled: boolean;
  isStreaming: boolean;
}

export function SubagentThread({ token, sessionKey, task, historyEnabled, isStreaming }: SubagentThreadProps) {
  const { messages, loading, failed, activeTurnId, retry } = useSubagentThread({ token, sessionKey, task, historyEnabled });
  return <SubagentThreadView messages={messages} loading={loading} failed={failed} isStreaming={isStreaming}
    activeTurnId={activeTurnId} runStartedAt={task.created_at} onRetry={retry} />;
}
