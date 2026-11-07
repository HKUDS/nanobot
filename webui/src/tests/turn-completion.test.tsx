import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
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

const EMPTY_MESSAGES: UIMessage[] = [];
const CHAT_ID = "completed-turn";
const TURN_ID = "turn-1";

function setup() {
  const socket = new TestSocket();
  const client = new NanobotClient({
    url: "ws://test", reconnect: false,
    socketFactory: () => socket as unknown as WebSocket,
  });
  client.connect();
  socket.open();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ClientProvider client={client} token="test">{children}</ClientProvider>
  );
  const running: InboundEvent = {
    event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID,
    status: "running", started_at: 1_700_000_000,
  };
  return { socket, client, wrapper, running };
}

describe("completed turn event ordering", () => {
  it("does not restore busy state from pending history delivered after completion", () => {
    const { socket, client, wrapper, running } = setup();
    const staleHistory: UIMessage[] = [{
      id: "persisted-user", role: "user", content: "original request", turnId: TURN_ID, createdAt: 0,
    }];
    const { result, rerender, unmount } = renderHook(
      ({ pending, history, active }: { pending: boolean; history: UIMessage[]; active: string | null }) =>
        useNanobotStream(CHAT_ID, history, pending, undefined, undefined, [], undefined, active),
      { wrapper, initialProps: { pending: false, history: EMPTY_MESSAGES, active: null as string | null } },
    );
    act(() => {
      socket.receive(running);
      socket.receive({ event: "stream_end", chat_id: CHAT_ID, turn_id: TURN_ID, text: "done" });
      socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
    });
    expect(result.current.isStreaming).toBe(false);
    rerender({ pending: true, history: staleHistory, active: TURN_ID });
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    act(() => socket.receive({
      ...running, turn_id: "next-turn", started_at: 1_700_000_100,
    }));
    rerender({ pending: false, history: staleHistory, active: null });
    expect(result.current.isStreaming).toBe(true);
    expect(client.getRunTurnId(CHAT_ID)).toBe("next-turn");
    unmount();
    client.close();
  });

  it("shares optimistic activity before a gateway start clock exists", () => {
    const { socket, client, wrapper } = setup();
    const status = vi.fn();
    client.onRunStatus(status);
    const { result, unmount } = renderHook(
      () => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper },
    );
    act(() => { result.current.send("new request"); });
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.runStartedAt).toBeNull();
    expect(status).toHaveBeenLastCalledWith(CHAT_ID,
      expect.objectContaining({ active: true, startedAt: null }));
    const turnId = client.getRunTurnId(CHAT_ID)!;
    act(() => socket.receive({
      event: "turn_end", chat_id: CHAT_ID, turn_id: turnId,
    }));
    expect(result.current.isStreaming).toBe(false);
    expect(status).toHaveBeenLastCalledWith(CHAT_ID,
      expect.objectContaining({ active: false, startedAt: null }));
    unmount();
    client.close();
  });

  it("restores the canonical owner rather than a steering input at the history tail", () => {
    const { socket, client, wrapper } = setup();
    const initial: UIMessage[] = [{
      id: "steering", role: "user", content: "additional guidance", turnId: "input-2", createdAt: Date.now(),
    }];
    const { result, unmount } = renderHook(
      () => useNanobotStream(CHAT_ID, initial, true, undefined, undefined, [], undefined, TURN_ID), { wrapper },
    );
    expect(result.current.isStreaming).toBe(true);
    expect(client.getRunTurnId(CHAT_ID)).toBe(TURN_ID);
    act(() => socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID }));
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    unmount();
    client.close();
  });

  it.each(["turn_end", "idle", "stop", "snapshot", "idle snapshot"] as const)(
    "keeps %s terminal despite late lifecycle and ownership frames",
    (terminal) => {
      const { socket, client, wrapper, running } = setup();
      const { result, unmount } = renderHook(
        () => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper },
      );
      act(() => socket.receive(running));
      act(() => {
        if (terminal === "stop") result.current.stop();
        else if (terminal === "snapshot") {
          client.reconcileCanonicalCompletion(CHAT_ID, client.getRunGeneration(CHAT_ID), [TURN_ID]);
        } else if (terminal === "idle snapshot") {
          expect(client.reconcileCanonicalCompletion(CHAT_ID, client.getRunGeneration(CHAT_ID), [], {
            observedTurnIds: [TURN_ID], hasPendingToolCalls: false, activeTurnId: null,
          })).toBe(true);
        } else socket.receive(terminal === "idle"
          ? { event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID, status: "idle" }
          : { event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
      });
      expect(result.current.isStreaming).toBe(false);

      act(() => {
        socket.receive(running);
        socket.receive({
          event: "user_message", chat_id: CHAT_ID, turn_id: TURN_ID,
          text: "late original task", starts_turn: true,
        });
        socket.receive({
          event: "user_message", chat_id: CHAT_ID, turn_id: "input-2",
          text: "additional context", starts_turn: false,
          active_turn_id: TURN_ID, started_at: 1_700_000_000,
        });
        socket.receive({
          event: "message_accepted", chat_id: CHAT_ID, turn_id: "input-2",
          starts_turn: false, active_turn_id: TURN_ID, started_at: 1_700_000_000,
        });
        socket.receive({ event: "stream_end", chat_id: CHAT_ID, turn_id: TURN_ID, text: "late" });
      });
      expect(result.current.isStreaming).toBe(false);
      expect(result.current.runStartedAt).toBeNull();
      expect(client.getRunStartedAt(CHAT_ID)).toBeNull();
      expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
      expect(result.current.messages.some((message) => message.content === "additional context")).toBe(true);

      act(() => socket.receive({
        event: "goal_status", chat_id: CHAT_ID, turn_id: "turn-3",
        status: "running", started_at: 1_700_000_100,
      }));
      act(() => {
        socket.receive(running);
        socket.receive({
          event: "message_accepted", chat_id: CHAT_ID, turn_id: "input-2",
          starts_turn: false, active_turn_id: TURN_ID, started_at: 1_700_000_000,
        });
      });
      expect(result.current.isStreaming).toBe(true);
      expect(client.getRunTurnId(CHAT_ID)).toBe("turn-3");
      expect(result.current.runStartedAt).toBe(1_700_000_100);
      unmount();
      client.close();
    },
  );

  it("settles a local new-run guess admitted as steering of an already completed owner", () => {
    const { socket, client, wrapper, running } = setup();
    const { result, unmount } = renderHook(
      () => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper },
    );
    act(() => {
      socket.receive(running);
      socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
    });
    act(() => result.current.send("additional context"));
    const inputTurnId = client.getRunTurnId(CHAT_ID)!;
    expect(result.current.isStreaming).toBe(true);
    act(() => socket.receive({
      event: "message_accepted", chat_id: CHAT_ID, turn_id: inputTurnId,
      active_turn_id: TURN_ID, starts_turn: false, started_at: 1_700_000_000,
    }));
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    expect(result.current.messages.find((message) => message.content === "additional context"))
      .toMatchObject({ deliveryStatus: "accepted" });
    unmount();
    client.close();
  });

  it("preserves a final answer and turn outcome arriving after idle", () => {
    const { socket, client, wrapper, running } = setup();
    const onTurnEnd = vi.fn();
    const { result, unmount } = renderHook(
      () => useNanobotStream(CHAT_ID, EMPTY_MESSAGES, false, onTurnEnd), { wrapper },
    );
    act(() => {
      socket.receive(running);
      socket.receive({ event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID, status: "idle" });
      socket.receive({ event: "message", chat_id: CHAT_ID, turn_id: TURN_ID, text: "final answer" });
      socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID, latency_ms: 42 });
    });
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.find((message) => message.content === "final answer"))
      .toMatchObject({ latencyMs: 42 });
    expect(onTurnEnd).toHaveBeenCalledOnce();
    unmount();
    client.close();
  });

  it("sends queued guidance once when completion and an old broadcast are batched", () => {
    const { socket, client, running } = setup();
    const onSend = vi.fn();
    function Composer() {
      const stream = useNanobotStream(CHAT_ID, EMPTY_MESSAGES);
      return <ThreadComposer onSend={onSend} onStop={stream.stop}
        isStreaming={stream.isStreaming || stream.runStartedAt !== null} />;
    }
    const { unmount } = render(
      <ClientProvider client={client} token="test"><Composer /></ClientProvider>,
    );
    act(() => socket.receive(running));
    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    act(() => {
      socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
      socket.receive({ event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID, status: "idle" });
      socket.receive({
        event: "user_message", chat_id: CHAT_ID, turn_id: TURN_ID, text: "original task",
        starts_turn: true, active_turn_id: TURN_ID, started_at: 1_700_000_000,
      });
    });
    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("follow-up");
    expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
    act(() => socket.receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID }));
    expect(onSend).toHaveBeenCalledOnce();
    unmount();
    client.close();
  });
});
