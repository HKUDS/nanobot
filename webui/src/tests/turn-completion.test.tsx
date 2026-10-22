import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import type { UIMessage } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";
import { createStreamClient } from "./stream-client";

const EMPTY_MESSAGES: UIMessage[] = [];
const CHAT_ID = "completed-turn";
const TURN_ID = "turn-1";

function setup() {
  const { client, receive, updateRuns, setConnected } = createStreamClient();
  updateRuns(CHAT_ID, []);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ClientProvider client={client} token="test">{children}</ClientProvider>
  );
  const running = (turnId = TURN_ID, startedAt: number | null = 1_700_000_000, phase: "queued" | "running" = "running") => (
    updateRuns(CHAT_ID, [{ run_id: `owner:${turnId}`, turn_id: turnId, phase, started_at: startedAt }])
  );
  return { client, receive, wrapper, running, idle: () => updateRuns(CHAT_ID, []), setConnected };
}

describe("completed turn event ordering", () => {
  it("does not restore busy state from pending history delivered after completion", () => {
    const { receive, client, wrapper, running, idle } = setup();
    const staleHistory: UIMessage[] = [{
      id: "persisted-user", role: "user", content: "original request", turnId: TURN_ID, createdAt: 0,
    }];
    const { result, rerender, unmount } = renderHook(
      ({ history }: { history: UIMessage[] }) => useNanobotStream(CHAT_ID, history),
      { wrapper, initialProps: { history: EMPTY_MESSAGES } },
    );
    act(() => {
      running();
      receive({ event: "stream_end", chat_id: CHAT_ID, turn_id: TURN_ID, text: "done" });
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
      idle();
    });
    expect(result.current.isStreaming).toBe(false);
    rerender({ history: staleHistory });
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    act(() => running("next-turn", 1_700_000_100));
    rerender({ history: staleHistory });
    expect(result.current.isStreaming).toBe(true);
    expect(client.getRunTurnId(CHAT_ID)).toBe("next-turn");
    unmount();
    client.close();
  });

  it("separates local delivery from server queue admission before a start clock exists", () => {
    const { receive, client, wrapper, running, idle } = setup();
    const status = vi.fn();
    client.onRunStatus(status);
    const { result, unmount } = renderHook(() => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper });
    act(() => { result.current.send("new request"); });
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.runState).toMatchObject({ active: false, delivery: "sending" });
    const turnId = client.getRunTurnId(CHAT_ID)!;
    act(() => running(turnId, null, "queued"));
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.runStartedAt).toBeNull();
    expect(status).toHaveBeenLastCalledWith(CHAT_ID,
      expect.objectContaining({ active: true, phase: "queued", startedAt: null }));
    act(() => {
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: turnId });
      idle();
    });
    expect(result.current.isStreaming).toBe(false);
    expect(status).toHaveBeenLastCalledWith(CHAT_ID,
      expect.objectContaining({ active: false, startedAt: null }));
    unmount();
    client.close();
  });

  it("restores the backend owner rather than a steering input at the history tail", () => {
    const { receive, client, wrapper, running, idle } = setup();
    const initial: UIMessage[] = [{
      id: "steering", role: "user", content: "additional guidance", turnId: "input-2", createdAt: Date.now(),
    }];
    const { result, unmount } = renderHook(() => useNanobotStream(CHAT_ID, initial), { wrapper });
    expect(result.current.isStreaming).toBe(false);
    expect(client.getRunTurnId(CHAT_ID)).toBeNull();
    act(() => running());
    expect(result.current.isStreaming).toBe(true);
    expect(client.getRunTurnId(CHAT_ID)).toBe(TURN_ID);
    act(() => {
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
      idle();
    });
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    unmount();
    client.close();
  });

  it.each(["turn_end", "canonical result"] as const)(
    "keeps %s terminal despite late lifecycle and ownership frames",
    (terminal) => {
      const { receive, client, wrapper, running, idle } = setup();
      const { result, unmount } = renderHook(() => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper });
      let oldSnapshot: ReturnType<typeof running>;
      act(() => { oldSnapshot = running(); });
      act(() => {
        if (terminal === "canonical result") {
          client.reconcileCanonicalCompletion(CHAT_ID, client.getRunGeneration(CHAT_ID), [TURN_ID]);
        } else receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
        idle();
      });
      expect(result.current.isStreaming).toBe(false);
      const lateBroadcasts = () => {
        receive({ event: "run_state", chat_id: CHAT_ID, run_state: oldSnapshot });
        receive({ event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID, status: "running", started_at: 1_700_000_000 });
        receive({ event: "user_message", chat_id: CHAT_ID, turn_id: TURN_ID, text: "late original task", starts_turn: true });
        receive({ event: "user_message", chat_id: CHAT_ID, turn_id: "input-2", text: "additional context",
          starts_turn: false, active_turn_id: TURN_ID, started_at: 1_700_000_000 });
        receive({ event: "message_accepted", chat_id: CHAT_ID, turn_id: "input-2",
          starts_turn: false, active_turn_id: TURN_ID, started_at: 1_700_000_000 });
      };
      act(lateBroadcasts);
      expect(result.current.isStreaming).toBe(false);
      expect(result.current.runStartedAt).toBeNull();
      expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
      expect(result.current.messages.some((message) => message.content === "additional context")).toBe(true);
      act(() => running("turn-3", 1_700_000_100));
      act(lateBroadcasts);
      expect(result.current.isStreaming).toBe(true);
      expect(client.getRunTurnId(CHAT_ID)).toBe("turn-3");
      expect(result.current.runStartedAt).toBe(1_700_000_100);
      unmount();
      client.close();
    },
  );

  it("does not settle an idle execution snapshot or a history page without a complete result", () => {
    const { receive, client, wrapper, running, idle } = setup();
    const { result, unmount } = renderHook(() => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper });
    act(() => {
      running();
      receive({ event: "delta", chat_id: CHAT_ID, turn_id: TURN_ID, text: "partial" });
      idle();
    });
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(true);
    expect(client.reconcileCanonicalCompletion(CHAT_ID, client.getRunGeneration(CHAT_ID), [], {
      observedTurnIds: [TURN_ID], hasPendingToolCalls: false, activeTurnId: null, completionIdsProvided: true,
    })).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(true);
    act(() => receive({ event: "stream_end", chat_id: CHAT_ID, turn_id: TURN_ID, text: "final answer" }));
    expect(result.current.messages.at(-1)).toMatchObject({ content: "final answer", isStreaming: true });
    act(() => receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID, latency_ms: 42 }));
    expect(result.current.messages.at(-1)).toMatchObject({ content: "final answer", latencyMs: 42, isStreaming: false });
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    unmount();
    client.close();
  });

  it("keeps a new local input separate when it is admitted as steering of a completed owner", () => {
    const { receive, client, wrapper, running, idle } = setup();
    const { result, unmount } = renderHook(() => useNanobotStream(CHAT_ID, EMPTY_MESSAGES), { wrapper });
    act(() => {
      running();
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
      idle();
    });
    act(() => result.current.send("additional context"));
    const inputTurnId = client.getRunTurnId(CHAT_ID)!;
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.runState?.delivery).toBe("sending");
    act(() => receive({ event: "message_accepted", chat_id: CHAT_ID, turn_id: inputTurnId,
      active_turn_id: TURN_ID, starts_turn: false, started_at: 1_700_000_000 }));
    expect(result.current.isStreaming).toBe(false);
    expect(client.hasUnsettledRun(CHAT_ID)).toBe(false);
    expect(result.current.messages.find((message) => message.content === "additional context"))
      .toMatchObject({ deliveryStatus: "accepted" });
    unmount();
    client.close();
  });

  it("sends queued guidance once, only after final text commits and the backend is freshly idle", () => {
    const { receive, client, running, idle, setConnected } = setup();
    const onSend = vi.fn(() => {
      expect(screen.getByText("final answer")).toBeInTheDocument();
      return true;
    });
    function Composer() {
      const stream = useNanobotStream(CHAT_ID, EMPTY_MESSAGES);
      const state = stream.runState;
      const completedTurnIds = client.isRunCompleted(CHAT_ID, TURN_ID) ? [TURN_ID] : [];
      return <>
        {stream.messages.map((message) => <p key={message.id}>{message.content}</p>)}
        <ThreadComposer onSend={onSend} onStop={stream.stop} isStreaming={stream.isStreaming}
          activeTurnId={stream.isStreaming ? TURN_ID : null} completedTurnIds={completedTurnIds}
          queueAutoSendAllowed={state?.freshness === "fresh" && !state.active && !state.unsettled
            && state.delivery === "none" && !state.cancelPending} />
      </>;
    }
    const { unmount } = render(<ClientProvider client={client} token="test"><Composer /></ClientProvider>);
    let oldSnapshot: ReturnType<typeof running>;
    act(() => { oldSnapshot = running(); });
    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    act(() => idle());
    expect(onSend).not.toHaveBeenCalled();
    act(() => receive({ event: "stream_end", chat_id: CHAT_ID, turn_id: TURN_ID, text: "final answer" }));
    expect(onSend).not.toHaveBeenCalled();
    act(() => setConnected(false));
    expect(onSend).not.toHaveBeenCalled();
    act(() => {
      setConnected(true);
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
    });
    // A complete reply cannot authorize the queue while the runtime baseline is syncing.
    expect(onSend).not.toHaveBeenCalled();
    act(() => idle());
    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("follow-up");
    expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
    act(() => {
      receive({ event: "run_state", chat_id: CHAT_ID, run_state: oldSnapshot });
      receive({ event: "goal_status", chat_id: CHAT_ID, turn_id: TURN_ID, status: "running" });
      receive({ event: "turn_end", chat_id: CHAT_ID, turn_id: TURN_ID });
    });
    expect(onSend).toHaveBeenCalledOnce();
    unmount();
    client.close();
  });
});
