import { useState } from "react";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { ExecSessionCommandsContext } from "@/components/thread/activity/exec-session-context";
import { execSessionCommands } from "@/components/thread/activity/exec-session-model";
import { formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

const id = "012345abcdef";
const running = `Process running. session_id: ${id}\nRuntime remaining: 100.0s\nElapsed: 1.0s`;
const history: UIMessage[] = [{
  id: "source", role: "tool", kind: "trace", content: "exec()", createdAt: 1,
  toolEvents: [{ name: "exec", call_id: "source", phase: "end", arguments: { command: "curl -u alice:secret-value https://example.invalid" },
    result: `${running}\nInitial wait ended; session remains active.` }],
}];
const commands = execSessionCommands(history);
type Stage = "waiting" | "running" | "input" | "failed" | "many";

function sessionMessage(stage: Stage): UIMessage {
  let events: ToolProgressEvent[];
  if (stage === "many") {
    events = Array.from({ length: 25 }, (_, index) => ({
      name: "exec_session", call_id: `poll-${index}`, phase: "end", arguments: { session_id: id }, result: running,
    }));
  } else {
    events = [{ name: "exec_session", call_id: "poll", arguments: { session_id: id, ...(stage === "input" ? { input: "private-stdin" } : {}) },
      phase: stage === "waiting" ? "start" : "end",
      ...(stage === "waiting" ? {} : { result: stage === "failed" ? "Exit code: 7\nElapsed: 2.0s" : running }) }];
  }
  const traces = events.map((event) => formatToolCallTrace(event)!);
  return { id: "trace", role: "tool", kind: "trace", content: traces[0], traces, toolEvents: events, createdAt: 2 };
}

export function ExecSessionFixture() {
  const [stage, setStage] = useState<Stage>("waiting");
  return <main className="mx-auto max-w-2xl space-y-6 p-6">
    <nav className="flex flex-wrap gap-3" aria-label="Fixture controls">
      {(["waiting", "running", "input", "failed", "many"] as const).map((value) => (
        <button key={value} onClick={() => setStage(value)}>{value}</button>
      ))}
    </nav>
    <section aria-label="Command activity">
      <ExecSessionCommandsContext.Provider value={commands}>
        <AgentActivityCluster messages={[sessionMessage(stage)]} isTurnStreaming hasBodyBelow={false} />
      </ExecSessionCommandsContext.Provider>
    </section>
  </main>;
}
