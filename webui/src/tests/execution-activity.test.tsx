import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { setAppLanguage } from "@/i18n";
import { createThreadProjectionState, projectThreadEvent, projectThreadEvents } from "@/lib/thread-event-projection";
import { toolTraceLinesFromEvents } from "@/lib/tool-traces";
import type { ExecutionProgressEvent, ThreadProjectionEvent } from "@/lib/types";

function execution(overrides: Partial<ExecutionProgressEvent> = {}): ExecutionProgressEvent {
  return {
    version: 2, activity: "execution", name: "command_launch", call_id: "launch",
    phase: "start", state: "starting", operation: "launch", counts_as_operation: true,
    command: "bun test", ...overrides,
  };
}

function message(event: ExecutionProgressEvent): ThreadProjectionEvent {
  return { event: "message", kind: "execution", chat_id: "preview", text: "safe text fallback", tool_events: [event] };
}

function cluster(events: ThreadProjectionEvent[]) {
  return <AgentActivityCluster
    messages={projectThreadEvents(events)} isTurnStreaming={false} hasBodyBelow={false} expanded
  />;
}

describe("public execution activity", () => {
  it("keeps semantic activity in live and replay without synthesizing a protocol trace", async () => {
    await setAppLanguage("zh-CN");
    const records = [
      message(execution()),
      message(execution({ phase: "end", state: "started" })),
      message(execution({
        name: "command_result", call_id: "observe-final", phase: "end", state: "completed",
        operation: "observe", counts_as_operation: false, command: null,
      })),
    ];
    const replay = projectThreadEvents(records);
    let live = createThreadProjectionState([]);
    for (const event of records) live = projectThreadEvent(live, event, { now: 1, createId: () => "live" });
    expect(live.messages[0].toolEvents).toEqual(replay[0].toolEvents);
    expect(replay[0].traces).toEqual([]);
    expect(toolTraceLinesFromEvents(replay[0].toolEvents)).toEqual([]);
    expect(replay[0].toolEvents).toHaveLength(2);
    const { container } = render(cluster(records));
    expect(screen.getByText("命令已启动")).toBeInTheDocument();
    expect(screen.getByText("命令已完成")).toBeInTheDocument();
    expect(container.textContent).not.toContain("继续命令");
    expect(container.textContent).not.toContain("2 个操作");
    expect(container.textContent).not.toContain("observe-final");
    expect(container.textContent).not.toContain("safe text fallback");
  });

  it("preserves visible answer slices around execution notices in a real tool-loop sequence", () => {
    const records: ThreadProjectionEvent[] = [
      { event: "user_message", chat_id: "preview", text: "run", starts_turn: true },
      { event: "delta", chat_id: "preview", text: "Before command." },
      { event: "stream_end", chat_id: "preview", text: "Before command.", resuming: true },
      message(execution()),
      message(execution({ phase: "end", state: "started" })),
      { event: "stream_end", chat_id: "preview", resuming: true },
      message(execution({ name: "command_result", call_id: "result", phase: "end", state: "completed", counts_as_operation: false })),
      { event: "delta", chat_id: "preview", text: "After command." },
      { event: "stream_end", chat_id: "preview", text: "After command." },
      { event: "turn_end", chat_id: "preview" },
    ];
    const projected = projectThreadEvents(records);
    expect(projected.filter(item => item.role === "assistant" && item.content).map(item => item.content))
      .toEqual(["Before command.", "After command."]);
    expect(projected.flatMap(item => item.toolEvents ?? []).map(item => (item as ExecutionProgressEvent).state))
      .toEqual(["started", "completed"]);
  });

  it("shows a standalone failure notice even though it is not an operation", async () => {
    await setAppLanguage("zh-CN");
    render(cluster([message(execution({
      phase: "error", state: "control_failed", operation: "input", counts_as_operation: false,
      command: null,
    }))]));
    expect(screen.getByText("命令输入发送失败")).toBeInTheDocument();
  });

  it("renders real exit failure and incomplete output without exposing command secrets", async () => {
    await setAppLanguage("en");
    const event = execution({ phase: "error", state: "failed", exit_code: 7,
      output_incomplete: true, command: "cli --token private-token-value" });
    const { container } = render(cluster([message(event), message(event)]));
    expect(screen.getAllByText("Command failed")).toHaveLength(1);
    expect(container.textContent).toContain("Exit code 7");
    expect(container.textContent).toContain("Output may be incomplete");
    expect(container.textContent).not.toContain("private-token-value");
  });
});
