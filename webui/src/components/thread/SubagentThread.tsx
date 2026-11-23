import { useMemo } from "react";
import { SubagentThreadView } from "@/components/thread/SubagentThreadView";
import { ExecSessionCommandsContext } from "@/components/thread/activity/exec-session-context";
import { execSessionCommands } from "@/components/thread/activity/exec-session-model";
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
  const { messages, loading, error, activeTurnId, retry } = useSubagentThread({ token, sessionKey, task, historyEnabled });
  const commands = useMemo(() => execSessionCommands(messages), [messages]);
  return <ExecSessionCommandsContext.Provider value={commands}>
    <SubagentThreadView messages={messages} loading={loading} error={error} isStreaming={isStreaming}
      activeTurnId={activeTurnId} runStartedAt={task.created_at} onRetry={retry} />
  </ExecSessionCommandsContext.Provider>;
}
