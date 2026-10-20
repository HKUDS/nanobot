import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import { NanobotClient } from "@/lib/nanobot-client";
import type { InboundEvent, UIMessage } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

class TestSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(event: InboundEvent) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }
}

const CHAT_ID = "replay-ownership";
const TURN_ID = "running-turn";
const INITIAL_MESSAGES: UIMessage[] = [
  { id: "prompt", role: "user", content: "Read the fixtures", turnId: TURN_ID, createdAt: 1_700_000_000_000 },
];

function toolMessage(callId: string): InboundEvent {
  return {
    event: "message", chat_id: CHAT_ID, turn_id: TURN_ID,
    kind: "tool_hint", text: `read_file(${callId}.txt)`,
    tool_events: [{
      call_id: callId, name: "read_file", phase: "end",
      arguments: { path: `${callId}.txt` }, result: `Contents of ${callId}`,
    }],
  };
}

function Thread({ children }: { children?: ReactNode }) {
  const { messages } = useNanobotStream(CHAT_ID, INITIAL_MESSAGES);
  return <><output data-testid="messages">{JSON.stringify(messages)}</output>{children}</>;
}

function displayedCalls(): string[] {
  const messages: UIMessage[] = JSON.parse(screen.getByTestId("messages").textContent!);
  return messages.flatMap((message) => message.toolEvents?.map((event) => {
    if (event.call_id === undefined) throw new Error("Expected a transcript tool call id");
    return event.call_id;
  }) ?? []);
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("transcript replay with real task and stream subscriptions", () => {
  it("retains transcript events while only the task observer is mounted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ tasks: [] }))));
    const socket = new TestSocket();
    const client = new NanobotClient({
      url: "ws://test", reconnect: false,
      socketFactory: () => socket as unknown as WebSocket,
    });
    client.connect();
    socket.open();
    const tree = (showThread: boolean) => (
      <ClientProvider client={client} token="test">
        <SubagentTasksProvider client={client} sessionKey={`websocket:${CHAT_ID}`}
          token="test" enabled liveEvents>{showThread && <Thread />}</SubagentTasksProvider>
      </ClientProvider>
    );
    const view = render(tree(false));
    try {
      await act(async () => {
        socket.receive(toolMessage("while-away-b"));
        socket.receive(toolMessage("while-away-c"));
      });
      view.rerender(tree(true));
      expect(displayedCalls()).toEqual(["while-away-b", "while-away-c"]);
    } finally {
      view.unmount();
      client.close();
    }
  });

  it.each(["tasks first", "transcript first"])(
    "retains queued tools when %s subscribes on topic return",
    async (order) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ tasks: [] }))));
      const socket = new TestSocket();
      const client = new NanobotClient({
        url: "ws://test", reconnect: false,
        socketFactory: () => socket as unknown as WebSocket,
      });
      client.connect();
      socket.open();
      socket.receive({
        event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID,
        status: "running", started_at: 1_700_000_000,
      });
      socket.receive(toolMessage("while-away-b"));
      socket.receive(toolMessage("while-away-c"));
      const tasks = (children?: ReactNode) => (
        <SubagentTasksProvider client={client} sessionKey={`websocket:${CHAT_ID}`}
          token="test" enabled liveEvents>{children}</SubagentTasksProvider>
      );
      const view = render(
        <ClientProvider client={client} token="test">
          {order === "tasks first" ? <Thread>{tasks()}</Thread> : tasks(<Thread />)}
        </ClientProvider>,
      );
      try {
        await act(async () => { socket.receive(toolMessage("after-return-d")); });
        expect(displayedCalls()).toEqual(["while-away-b", "while-away-c", "after-return-d"]);
      } finally {
        view.unmount();
        client.close();
      }
    },
  );
});
