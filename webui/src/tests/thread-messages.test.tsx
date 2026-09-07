import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assistantForkFlags,
  buildDisplayUnits,
  ThreadMessages,
  unitKeysForDisplay,
} from "@/components/thread/ThreadMessages";
import { preloadMarkdownText } from "@/components/MarkdownText";
import type { UIMessage } from "@/lib/types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("ThreadMessages", () => {
  it("shows optimistic turn progress in the thread before the first agent output", () => {
    vi.useFakeTimers();
    const now = new Date("2026-08-13T10:00:05.000Z").getTime();
    vi.setSystemTime(now);
    const prompt: UIMessage = {
      id: "u-optimistic",
      role: "user",
      content: "check this",
      turnId: "turn-optimistic",
      turnPhase: "user",
      deliveryStatus: "sending",
      createdAt: now - 5_000,
    };
    const { rerender } = render(
      <ThreadMessages
        messages={[prompt]}
        isStreaming
        activeTurnId="turn-optimistic"
        runStartedAt={(now - 5_000) / 1000}
      />,
    );

    expect(screen.getByRole("status", { name: "Working for 5s" })).toBeInTheDocument();

    rerender(
      <ThreadMessages
        messages={[
          { ...prompt, deliveryStatus: "accepted" },
          {
            id: "t-optimistic",
            role: "tool",
            kind: "trace",
            content: "web_search()",
            traces: ["web_search()"],
            turnId: "turn-optimistic",
            turnPhase: "activity",
            createdAt: now,
          },
        ]}
        isStreaming
        activeTurnId="turn-optimistic"
        runStartedAt={(now - 5_000) / 1000}
      />,
    );

    expect(screen.getByRole("button", { name: "Working for 5s" })).toBeInTheDocument();
  });

  it("does not move a mounted tail answer into offscreen rendering on the next turn", () => {
    const completed: UIMessage[] = [
      { id: "u1", role: "user", content: "question", createdAt: 1 },
      { id: "a1", role: "assistant", content: "latest answer", createdAt: 2 },
    ];
    const { rerender } = render(
      <ThreadMessages messages={completed} isStreaming={false} />,
    );

    expect(screen.getByText("latest answer").closest(".thread-render-unit")).toBeNull();

    rerender(
      <ThreadMessages
        messages={[
          ...completed,
          { id: "u2", role: "user", content: "next question", createdAt: 3 },
        ]}
        isStreaming
      />,
    );

    expect(screen.getByText("latest answer").closest(".thread-render-unit")).toBeNull();
  });

  it("still defers historical non-tail answers on their initial render", () => {
    render(
      <ThreadMessages
        messages={[
          { id: "u1", role: "user", content: "old question", createdAt: 1 },
          { id: "a1", role: "assistant", content: "historical answer", createdAt: 2 },
          { id: "u2", role: "user", content: "latest question", createdAt: 3 },
        ]}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("historical answer").closest(".thread-render-unit")).not.toBeNull();
  });

  it("preserves an answer's markdown tree across completion and the next prompt", async () => {
    await act(async () => {
      await preloadMarkdownText();
    });
    const turnId = "turn-1";
    const streaming: UIMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "question",
        createdAt: 1,
        turnId,
        turnPhase: "prompt",
      },
      {
        id: "live-answer",
        role: "assistant",
        content: "stable final answer",
        createdAt: 2,
        isStreaming: true,
        turnId,
        turnPhase: "answer",
      },
    ];
    const { container, rerender } = render(
      <ThreadMessages messages={streaming} isStreaming />,
    );
    await waitFor(
      () => expect(container.querySelector(".markdown-content")).not.toBeNull(),
      { timeout: 3_000 },
    );
    const paragraph = screen.getByText("stable final answer").closest("p");
    expect(paragraph).not.toBeNull();

    rerender(
      <ThreadMessages
        messages={[
          streaming[0],
          {
            ...streaming[1],
            id: "canonical-answer",
            isStreaming: false,
          },
        ]}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("stable final answer").closest("p")).toBe(paragraph);

    rerender(
      <ThreadMessages
        messages={[
          streaming[0],
          {
            ...streaming[1],
            id: "canonical-answer",
            isStreaming: false,
          },
          {
            id: "u2",
            role: "user",
            content: "next question",
            createdAt: 3,
            turnId: "turn-2",
            turnPhase: "prompt",
          },
        ]}
        isStreaming
      />,
    );

    expect(screen.getByText("stable final answer").closest("p")).toBe(paragraph);
  });

  it("keeps live Markdown mounted when a later tool activity arrives", async () => {
    await act(async () => {
      await preloadMarkdownText();
    });
    const turnId = "turn-live-order";
    const prompt: UIMessage = {
      id: "u-live",
      role: "user",
      content: "research this",
      createdAt: 1,
      turnId,
      turnPhase: "prompt",
      turnSeq: 0,
    };
    const commentary: UIMessage = {
      id: "a-commentary",
      role: "assistant",
      content: "**I will check that.**",
      createdAt: 2,
      isStreaming: false,
      turnId,
      turnPhase: "answer",
      turnSeq: 1,
    };
    const { rerender } = render(
      <ThreadMessages
        messages={[prompt, commentary]}
        isStreaming
        activeTurnId={turnId}
      />,
    );
    const paragraph = await screen.findByText("I will check that.");
    expect(paragraph.closest("[data-testid='activity-model-message']")).toBeNull();

    rerender(
      <ThreadMessages
        messages={[
          prompt,
          commentary,
          {
            id: "tool-live",
            role: "tool",
            kind: "trace",
            content: "web_search()",
            traces: ["web_search()"],
            createdAt: 3,
            turnId,
            turnPhase: "activity",
            turnSeq: 2,
          },
        ]}
        isStreaming
        activeTurnId={turnId}
      />,
    );

    expect(screen.getByText("I will check that.")).toBe(paragraph);
    expect(screen.getByText(/working/i)).toBeInTheDocument();
  });

  it("projects a turn in causal order independently of streaming state", () => {
    const turnId = "turn-causal-order";
    const messages: UIMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "inspect this",
        turnId,
        turnPhase: "user",
        turnSeq: 0,
        createdAt: 1,
      },
      {
        id: "a1",
        role: "assistant",
        content: "I will inspect it.",
        turnId,
        turnPhase: "answer",
        turnSeq: 1,
        createdAt: 2,
      },
      {
        id: "a2",
        role: "assistant",
        content: "Inspection complete.",
        turnId,
        turnPhase: "answer",
        turnSeq: 4,
        createdAt: 5,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "shell()",
        traces: ["shell()"],
        turnId,
        turnPhase: "activity",
        turnSeq: 2,
        createdAt: 3,
      },
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "checking output",
        turnId,
        turnPhase: "reasoning",
        turnSeq: 3,
        createdAt: 4,
      },
    ];

    const units = buildDisplayUnits(messages);
    const order = (units: ReturnType<typeof buildDisplayUnits>) => units.map((unit) => (
      unit.type === "activity"
        ? `activity:${unit.messages.map((message) => message.id).join(",")}`
        : unit.message.id
    ));

    expect(order(units)).toEqual([
      "u1",
      "a1",
      "activity:t1,r1",
      "a2",
    ]);

    const { rerender } = render(
      <ThreadMessages messages={messages} isStreaming activeTurnId={turnId} />,
    );
    const firstAnswer = screen.getByText("I will inspect it.");
    const finalAnswer = screen.getByText("Inspection complete.");
    const liveActivity = screen.getByRole("button", { name: /working/i });
    expect(firstAnswer.compareDocumentPosition(liveActivity) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(liveActivity.compareDocumentPosition(finalAnswer) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();

    rerender(<ThreadMessages messages={messages} isStreaming={false} activeTurnId={null} />);
    const completedActivity = screen.getByRole("button", { name: /worked/i });
    expect(firstAnswer.compareDocumentPosition(completedActivity) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(completedActivity.compareDocumentPosition(finalAnswer) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("ignores a completed empty answer frame without splitting contiguous activity", () => {
    const turnId = "turn-empty-answer-frame";
    const segmentId = "activity-1";
    const messages: UIMessage[] = [
      {
        id: "user",
        role: "user",
        content: "reply ok, then check",
        turnId,
        turnPhase: "user",
        turnSeq: 1,
        createdAt: 1,
      },
      {
        id: "reasoning-before",
        role: "assistant",
        content: "",
        reasoning: "Planning confirmation",
        activitySegmentId: segmentId,
        turnId,
        turnPhase: "reasoning",
        turnSeq: 3,
        createdAt: 2,
      },
      {
        id: "ok",
        role: "assistant",
        content: "ok",
        reasoning: "Preparing first query",
        activitySegmentId: segmentId,
        turnId,
        turnPhase: "answer",
        turnSeq: 7,
        createdAt: 3,
      },
      {
        id: "first-tool",
        role: "tool",
        kind: "trace",
        content: "first()",
        traces: ["first()"],
        activitySegmentId: segmentId,
        turnId,
        turnPhase: "activity",
        turnSeq: 9,
        createdAt: 4,
      },
      {
        id: "empty-answer-frame",
        role: "assistant",
        content: "",
        isStreaming: false,
        turnId,
        turnPhase: "answer",
        turnSeq: 10,
        createdAt: 5,
      },
      {
        id: "second-tool",
        role: "tool",
        kind: "trace",
        content: "second()",
        traces: ["second()"],
        activitySegmentId: segmentId,
        turnId,
        turnPhase: "activity",
        turnSeq: 12,
        createdAt: 6,
      },
      {
        id: "final",
        role: "assistant",
        content: "finished",
        reasoning: "Summarizing result",
        activitySegmentId: segmentId,
        turnId,
        turnPhase: "answer",
        turnSeq: 113,
        createdAt: 7,
      },
    ];

    const units = buildDisplayUnits(messages);
    expect(units.map((unit) => (
      unit.type === "activity"
        ? `activity:${unit.messages.map((message) => message.id).join(",")}`
        : unit.message.id
    ))).toEqual([
      "user",
      "activity:reasoning-before,ok-reasoning",
      "ok",
      "activity:first-tool,second-tool,final-reasoning",
      "final",
    ]);
    expect(units.map((unit) => unit.sourceMessageCount)).toEqual([1, 1, 1, 3, 1]);

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    const activityShells = screen.getAllByRole("button", { name: /worked/i });
    const ok = screen.getByText("ok");
    const final = screen.getByText("finished");
    expect(activityShells).toHaveLength(2);
    expect(activityShells[0].compareDocumentPosition(ok) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(ok.compareDocumentPosition(activityShells[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(activityShells[1].compareDocumentPosition(final) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("keeps empty frame source counts on the nearest visible unit", () => {
    const emptyFrame: UIMessage = {
      id: "empty",
      role: "assistant",
      content: "",
      isStreaming: false,
      turnPhase: "answer",
      createdAt: 2,
    };
    const answerUnits = buildDisplayUnits([
      { id: "a1", role: "assistant", content: "first", createdAt: 1 },
      emptyFrame,
      { id: "a2", role: "assistant", content: "second", createdAt: 3 },
    ]);
    expect(answerUnits).toMatchObject([{
      type: "message",
      message: { content: "first\n\nsecond" },
      sourceMessageCount: 3,
    }]);

    const emptyTurnUnits = buildDisplayUnits([
      { id: "user", role: "user", content: "hello", createdAt: 1 },
      emptyFrame,
    ]);
    expect(emptyTurnUnits).toMatchObject([{
      type: "message",
      message: { id: "user" },
      sourceMessageCount: 2,
    }]);

    const streamingUnits = buildDisplayUnits([{
      ...emptyFrame,
      id: "streaming-placeholder",
      isStreaming: true,
    }]);
    expect(streamingUnits).toMatchObject([{
      type: "activity",
      messages: [{ id: "streaming-placeholder" }],
      sourceMessageCount: 1,
    }]);
  });

  it("offers a follow-up action for text selected within one completed answer", async () => {
    const onQuoteSelection = vi.fn();
    render(
      <ThreadMessages
        messages={[{
          id: "a1",
          role: "assistant",
          content: "The selected answer excerpt",
          createdAt: 1,
        }]}
        isStreaming={false}
        onQuoteSelection={onQuoteSelection}
      />,
    );

    const textNode = screen.getByText("The selected answer excerpt").firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 4);
    range.setEnd(textNode, 19);
    vi.spyOn(range, "getBoundingClientRect").mockReturnValue({
      left: 100,
      right: 240,
      top: 100,
      bottom: 120,
      width: 140,
      height: 20,
      x: 100,
      y: 100,
      toJSON: () => ({}),
    });
    const removeAllRanges = vi.fn();
    vi.spyOn(window, "getSelection").mockReturnValue({
      isCollapsed: false,
      rangeCount: 1,
      getRangeAt: () => range,
      toString: () => "selected answer",
      removeAllRanges,
    } as unknown as Selection);

    document.dispatchEvent(new Event("selectionchange"));
    const action = await screen.findByRole("button", { name: "Ask about this" });
    fireEvent.click(action);

    await waitFor(() => expect(onQuoteSelection).toHaveBeenCalledWith("selected answer"));
    expect(removeAllRanges).toHaveBeenCalled();
  });

  it("groups consecutive reasoning and tool rows into one timeline before the answer", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "thinking",
        reasoningStreaming: false,
        isStreaming: true,
        createdAt: Date.now(),
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        createdAt: Date.now(),
      },
      {
        id: "r2",
        role: "assistant",
        content: "",
        reasoning: "more thinking",
        reasoningStreaming: false,
        isStreaming: true,
        createdAt: Date.now(),
      },
      {
        id: "a1",
        role: "assistant",
        content: "final answer",
        createdAt: Date.now(),
      },
    ];

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    const rows = Array.from(container.firstElementChild?.children ?? []);

    expect(rows).toHaveLength(2);
    expect(rows[0]).not.toHaveClass("mt-2", "mt-4", "mt-5");
    expect(rows[1]).toHaveClass("mt-4");
  });

  it("renders a fork boundary divider after the copied history", () => {
    const messages: UIMessage[] = [
      { id: "u1", role: "user", content: "original", createdAt: 1 },
      { id: "a1", role: "assistant", content: "first answer", createdAt: 2 },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        createdAt: 3,
      },
      { id: "a2", role: "assistant", content: "second answer", createdAt: 4 },
      { id: "u2", role: "user", content: "branch prompt", createdAt: 5 },
    ];

    const { container } = render(
      <ThreadMessages
        messages={messages}
        forkBoundaryMessageCount={4}
      />,
    );

    const rows = Array.from(container.firstElementChild?.children ?? []);
    const dividerIndex = rows.findIndex((row) => row.textContent?.includes("Forked from history"));
    const branchPromptIndex = rows.findIndex((row) => row.textContent?.includes("branch prompt"));
    expect(dividerIndex).toBeGreaterThan(0);
    expect(dividerIndex).toBe(branchPromptIndex - 1);
  });

  it("keeps turn unit keys stable across replayed ids and mutable turn sequence", () => {
    const liveUnits = buildDisplayUnits([
      { id: "optimistic-user", role: "user", content: "go", turnId: "turn-1", turnPhase: "user", turnSeq: 0, createdAt: 1 },
      {
        id: "live-a1",
        role: "assistant",
        content: "first answer slice",
        turnId: "turn-1",
        turnPhase: "answer",
        turnSeq: 2,
        createdAt: 2,
      },
      {
        id: "live-a2",
        role: "assistant",
        content: "second answer slice",
        turnId: "turn-1",
        turnPhase: "answer",
        turnSeq: 20,
        createdAt: 3,
      },
    ]);
    const replayUnits = buildDisplayUnits([
      { id: "replayed-user", role: "user", content: "go", turnId: "turn-1", turnPhase: "user", turnSeq: 10, createdAt: 10 },
      { id: "replayed-a1", role: "assistant", content: "first answer slice", turnId: "turn-1", turnPhase: "answer", turnSeq: 11, createdAt: 11 },
      { id: "replayed-a2", role: "assistant", content: "second answer slice", turnId: "turn-1", turnPhase: "answer", turnSeq: 99, createdAt: 12 },
    ]);

    expect(unitKeysForDisplay(liveUnits)).toEqual(unitKeysForDisplay(replayUnits));
    expect(unitKeysForDisplay(liveUnits)).toEqual([
      "turn-turn-1-user",
      "turn-turn-1-answer-1",
    ]);
  });

  it("keeps file edits inside the single activity surface for a turn", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "first pass",
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "edit_file()",
        traces: ["edit_file()"],
        fileEdits: [{
          call_id: "call-edit",
          tool: "edit_file",
          path: "foo.txt",
          phase: "end",
          added: 2,
          deleted: 1,
          status: "done",
        }],
        activitySegmentId: "seg-1",
        createdAt: 2,
      },
      {
        id: "r2",
        role: "assistant",
        content: "",
        reasoning: "second pass",
        activitySegmentId: "seg-2",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(1);
    expect(units[0].type).toBe("activity");
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "r1",
      "t1",
      "r2",
    ]);
  });

  it("keeps ordinary tool activity in one activity block across segment ids", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "first pass",
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "read_file()",
        traces: ["read_file()"],
        activitySegmentId: "seg-1",
        createdAt: 2,
      },
      {
        id: "r2",
        role: "assistant",
        content: "",
        reasoning: "second pass",
        activitySegmentId: "seg-2",
        createdAt: 3,
      },
      {
        id: "t2",
        role: "tool",
        kind: "trace",
        content: "grep()",
        traces: ["grep()"],
        activitySegmentId: "seg-2",
        createdAt: 4,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(1);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "r1",
      "t1",
      "r2",
      "t2",
    ]);
  });

  it("keeps trailing activity after the completed assistant answer", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "I should do a fresh search.",
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "a1",
        role: "assistant",
        content: "Let me search the latest data.",
        createdAt: 2,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "Searching query: HKUDS/nanobot GitHub stars",
        traces: ["Searching query: HKUDS/nanobot GitHub stars"],
        activitySegmentId: "seg-2",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(3);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "r1",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "Let me search the latest data.",
      },
    });
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual([
      "t1",
    ]);
  });

  it("only marks the current activity timeline as live while streaming", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "first pass",
        reasoningStreaming: true,
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "edit_file()",
        traces: ["edit_file()"],
        fileEdits: [{
          call_id: "call-edit",
          tool: "edit_file",
          path: "foo.txt",
          phase: "start",
          added: 4,
          deleted: 1,
          approximate: true,
          status: "editing",
        }],
        activitySegmentId: "seg-1",
        createdAt: 2,
      },
      {
        id: "r2",
        role: "assistant",
        content: "",
        reasoning: "second pass",
        reasoningStreaming: true,
        activitySegmentId: "seg-2",
        createdAt: 3,
      },
    ];

    render(<ThreadMessages messages={messages} isStreaming />);

    expect(screen.getByLabelText(/editing foo\.txt/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/edited foo\.txt/i)).not.toBeInTheDocument();
  });

  it("times live activity from the user turn start", () => {
    vi.useFakeTimers();
    const startedAt = 1_700_000_000_000;
    vi.setSystemTime(startedAt + 230_000);
    const messages: UIMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "run it",
        turnId: "turn-1",
        turnPhase: "user",
        turnSeq: 1,
        createdAt: startedAt,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "exec()",
        traces: ["exec()"],
        turnId: "turn-1",
        turnPhase: "activity",
        turnSeq: 2,
        createdAt: startedAt + 220_000,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(
      units[1].type === "activity" ? units[1].startedAtMs : undefined,
    ).toBe(startedAt);

    render(<ThreadMessages messages={messages} isStreaming />);

    expect(screen.getByText("Working for 3m 50s")).toBeInTheDocument();
    expect(screen.queryByText("Working for 10s")).not.toBeInTheDocument();
  });

  it("keeps a guided run's timer on its original activity cluster", () => {
    vi.useFakeTimers();
    const startedAt = 1_700_000_000_000;
    vi.setSystemTime(startedAt + 215_000);
    const messages: UIMessage[] = [
      {
        id: "u-original",
        role: "user",
        content: "research this",
        turnId: "turn-original",
        turnPhase: "user",
        turnSeq: 0,
        createdAt: startedAt,
      },
      {
        id: "t-original",
        role: "tool",
        kind: "trace",
        content: "web_search()",
        traces: ["web_search()"],
        turnId: "turn-original",
        turnPhase: "activity",
        turnSeq: 1,
        createdAt: startedAt + 500,
      },
      {
        id: "a-original",
        role: "assistant",
        content: "Continuing the search.",
        latencyMs: 1_000,
        turnId: "turn-original",
        turnPhase: "answer",
        turnSeq: 2,
        createdAt: startedAt + 1_000,
      },
      {
        id: "u-guidance",
        role: "user",
        content: "How is it going?",
        turnId: "turn-guidance",
        turnPhase: "user",
        turnSeq: 0,
        createdAt: startedAt + 215_000,
      },
    ];

    render(
      <ThreadMessages
        messages={messages}
        isStreaming
        activeTurnId="turn-original"
        runStartedAt={startedAt / 1000}
      />,
    );

    expect(screen.getByText("Working for 3m 35s")).toBeInTheDocument();
    expect(screen.queryByText("Worked for 1s")).not.toBeInTheDocument();
    expect(screen.queryByText("Thinking for 3m 35s")).not.toBeInTheDocument();
  });

  it("folds final answer reasoning into the preceding activity timeline", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "search plan",
        reasoningStreaming: false,
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "web_search()",
        traces: ["web_search()"],
        createdAt: 2,
      },
      {
        id: "a1",
        role: "assistant",
        content: "final answer",
        reasoning: "summarize results",
        reasoningStreaming: false,
        latencyMs: 9_200,
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(2);
    expect(units[0]).toMatchObject({ type: "activity" });
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "r1",
      "t1",
      "a1-reasoning",
    ]);
    expect(units[0].type === "activity" ? units[0].messages.at(-1)?.latencyMs : undefined).toBe(9_200);
    expect(units[1]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "final answer",
      },
    });
    if (units[1].type === "message") {
      expect(units[1].message).not.toHaveProperty("reasoning");
    }

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    expect(screen.queryByRole("button", { name: /^thinking$/i })).not.toBeInTheDocument();
    expect(screen.getByText("Worked for 9s")).toBeInTheDocument();
    expect(screen.getByText("final answer")).toBeInTheDocument();
  });

  it("uses final turn latency when an earlier reasoning segment has its own latency", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "plan",
        reasoningStreaming: false,
        latencyMs: 3_000,
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "shell()",
        traces: ["shell()"],
        createdAt: 2,
      },
      {
        id: "a1",
        role: "assistant",
        content: "done",
        latencyMs: 20_000,
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units[0].type === "activity" ? units[0].turnLatencyMs : undefined).toBe(20_000);

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    expect(screen.getByText("Worked for 20s")).toBeInTheDocument();
    expect(screen.queryByText("Worked for 3s")).not.toBeInTheDocument();
  });

  it("keeps a streamed answer outside late activity when the prompt snapshot is absent", () => {
    const messages: UIMessage[] = [
      {
        id: "t0",
        role: "tool",
        kind: "trace",
        content: "Thinking",
        traces: ["Thinking"],
        activitySegmentId: "seg-live",
        createdAt: 1,
      },
      {
        id: "a1",
        role: "assistant",
        content: "partial answer",
        isStreaming: true,
        createdAt: 2,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "Reading api.github.com/repos/NousResearch/hermes-agent",
        traces: ["Reading api.github.com/repos/NousResearch/hermes-agent"],
        activitySegmentId: "seg-live",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(3);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "t0",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: { id: "a1", content: "partial answer" },
    });
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual([
      "t1",
    ]);

    render(<ThreadMessages messages={messages} isStreaming />);

    const answer = screen.getByText("partial answer");
    const liveActivity = screen.getByRole("button", { name: /working/i });
    expect(answer.closest("[data-testid='activity-model-message']")).toBeNull();
    expect(answer.compareDocumentPosition(liveActivity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps late activity after a completed assistant answer", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "checking weather",
        activitySegmentId: "seg-late",
        createdAt: 1,
      },
      {
        id: "a1",
        role: "assistant",
        content: "Hong Kong is hot today.",
        latencyMs: 161_000,
        createdAt: 2,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "Reading hko.gov.hk/en/wxinfo/currwx/current.htm",
        traces: ["Reading hko.gov.hk/en/wxinfo/currwx/current.htm"],
        activitySegmentId: "seg-late",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(3);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual(["r1"]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "Hong Kong is hot today.",
      },
    });
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual(["t1"]);

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    const answer = screen.getByText("Hong Kong is hot today.");
    const laterActivity = screen.getAllByRole("button", { name: /worked/i }).at(-1);
    expect(laterActivity).toBeTruthy();
    expect(answer.compareDocumentPosition(laterActivity!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps completed web-search activity on both sides of an answer", () => {
    const messages: UIMessage[] = [
      {
        id: "user",
        role: "user",
        content: "最近科隆major开打了，你知道不？",
        createdAt: 1,
      },
      {
        id: "thought",
        role: "assistant",
        content: "",
        reasoning: "I should verify the current event details.",
        activitySegmentId: "seg-major",
        createdAt: 2,
      },
      {
        id: "answer",
        role: "assistant",
        content: "知道，IEM Cologne Major 2026 今天开打了。",
        latencyMs: 18_000,
        createdAt: 3,
      },
      {
        id: "web",
        role: "tool",
        kind: "trace",
        content: "Searching query: 2026 Cologne Major esports started 科隆 Major 开打了 2026",
        traces: ["Searching query: 2026 Cologne Major esports started 科隆 Major 开打了 2026"],
        activitySegmentId: "seg-major",
        createdAt: 4,
      },
    ];

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    const activities = screen.getAllByRole("button", { name: /worked/i });
    const answer = screen.getByText("知道，IEM Cologne Major 2026 今天开打了。");
    expect(activities).toHaveLength(2);
    expect(activities[0].compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(answer.compareDocumentPosition(activities[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("preserves a completed prior turn's order while the next turn is streaming", () => {
    const messages: UIMessage[] = [
      {
        id: "thought",
        role: "assistant",
        content: "",
        reasoning: "I should verify the current event details.",
        activitySegmentId: "seg-major",
        createdAt: 1,
      },
      {
        id: "answer",
        role: "assistant",
        content: "Yep — IEM Cologne Major 2026 is in Cologne.",
        latencyMs: 20_000,
        createdAt: 2,
      },
      {
        id: "web",
        role: "tool",
        kind: "trace",
        content: "Searching query: site:counter-strike.net majors 2026",
        traces: ["Searching query: site:counter-strike.net majors 2026"],
        activitySegmentId: "seg-major",
        createdAt: 3,
      },
      {
        id: "next-user",
        role: "user",
        content: "看一下目前的赛果，整个表哥",
        createdAt: 4,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(4);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "thought",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: { id: "answer" },
    });
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual([
      "web",
    ]);
    expect(units[3]).toMatchObject({
      type: "message",
      message: { id: "next-user" },
    });
  });

  it("orders live turn activity by causal turn sequence before the final answer", () => {
    const messages: UIMessage[] = [
      {
        id: "web-1",
        role: "tool",
        kind: "trace",
        content: "Searching query: 2026 Counter-Strike 2 Major location",
        traces: ["Searching query: 2026 Counter-Strike 2 Major location"],
        turnId: "turn-major",
        turnSeq: 3,
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "answer",
        role: "assistant",
        content: "Yep — IEM Cologne Major 2026 is in Cologne.",
        isStreaming: true,
        turnId: "turn-major",
        turnSeq: 84,
        createdAt: 3,
      },
      {
        id: "web-2",
        role: "tool",
        kind: "trace",
        content: "Searching query: site:counter-strike.net majors 2026",
        traces: ["Searching query: site:counter-strike.net majors 2026"],
        turnId: "turn-major",
        turnSeq: 83,
        activitySegmentId: "seg-2",
        createdAt: 2,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(2);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "web-1",
      "web-2",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: { id: "answer" },
    });
  });

  it("renders interrupted pre-tool text as activity before the final answer", () => {
    const messages: UIMessage[] = [
      {
        id: "prelude",
        role: "assistant",
        content: "",
        reasoning: "I will inspect first.",
        isStreaming: false,
        activitySegmentId: "seg-1",
        createdAt: 1,
      },
      {
        id: "tool",
        role: "tool",
        kind: "trace",
        content: 'exec({"cmd":"ls"})',
        traces: ['exec({"cmd":"ls"})'],
        activitySegmentId: "seg-1",
        createdAt: 2,
      },
      {
        id: "final",
        role: "assistant",
        content: "Done. Open index.html to play.",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(2);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "prelude",
      "tool",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: {
        id: "final",
        content: "Done. Open index.html to play.",
      },
    });
  });

  it("passes assistant turn latency to the preceding completed activity timeline", () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "search plan",
        reasoningStreaming: false,
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "web_search()",
        traces: ["web_search()"],
        createdAt: 1,
      },
      {
        id: "a1",
        role: "assistant",
        content: "final answer",
        latencyMs: 14_800,
        createdAt: 1,
      },
    ];

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    expect(screen.getByText("Worked for 15s")).toBeInTheDocument();
    expect(screen.queryByText("Worked for 0s")).not.toBeInTheDocument();
  });

  it("keeps answer slices on either side of activity in generation order", () => {
    const messages: UIMessage[] = [
      {
        id: "early",
        role: "assistant",
        content: "starting…",
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        createdAt: 2,
      },
      {
        id: "late",
        role: "assistant",
        content: "final reply",
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);
    expect(units).toHaveLength(3);
    expect(units[0]).toMatchObject({
      type: "message",
      message: { id: "early", content: "starting…" },
      sourceMessageCount: 1,
    });
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual([
      "t1",
    ]);
    expect(units[1].sourceMessageCount).toBe(1);
    expect(units[2]).toMatchObject({
      type: "message",
      message: { id: "late", content: "final reply" },
      sourceMessageCount: 1,
    });

    render(
      <ThreadMessages
        messages={messages}
        isStreaming={false}
        onForkFromMessage={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Fork" })).toHaveLength(1);
    expect(screen.getByText("starting…").closest("[data-testid='activity-model-message']")).toBeNull();
    expect(screen.getByText("final reply").closest("[data-testid='activity-model-message']")).toBeNull();
  });

  it("keeps a media-only answer slice outside the activity surface", () => {
    const messages: UIMessage[] = [
      {
        id: "early",
        role: "assistant",
        content: "generated the file",
        turnPhase: "answer",
        createdAt: 1,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "write_file()",
        traces: ["write_file()"],
        turnPhase: "activity",
        createdAt: 2,
      },
      {
        id: "attachment",
        role: "assistant",
        content: "",
        media: [{ kind: "file", url: "/api/media/result.csv", name: "result.csv" }],
        turnPhase: "answer",
        isStreaming: false,
        createdAt: 3,
      },
    ];

    const units = buildDisplayUnits(messages);

    expect(units).toHaveLength(3);
    expect(units[0]).toMatchObject({
      type: "message",
      message: { id: "early", content: "generated the file" },
      sourceMessageCount: 1,
    });
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual([
      "t1",
    ]);
    expect(units[2]).toMatchObject({
      type: "message",
      message: {
        id: "attachment",
        content: "",
        media: [{ kind: "file", url: "/api/media/result.csv", name: "result.csv" }],
      },
      sourceMessageCount: 1,
    });

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    expect(screen.getByText("result.csv")).toBeInTheDocument();
  });

  it("hides current turn actions until turn_end", () => {
    const activeTurnId = "turn-2";
    const messages: UIMessage[] = [
      { id: "u1", role: "user", content: "old question", turnId: "turn-1", createdAt: 1 },
      { id: "a1", role: "assistant", content: "old answer", turnId: "turn-1", createdAt: 2 },
      { id: "u2", role: "user", content: "new question", turnId: activeTurnId, createdAt: 3 },
      {
        id: "a2",
        role: "assistant",
        content: "first answer slice",
        turnId: activeTurnId,
        createdAt: 4,
      },
      {
        id: "t2",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        turnId: activeTurnId,
        createdAt: 5,
      },
      {
        id: "a3",
        role: "assistant",
        content: "second answer slice",
        turnId: activeTurnId,
        createdAt: 6,
      },
    ];
    const props = { messages, onForkFromMessage: vi.fn() };
    const { container, rerender } = render(
      <ThreadMessages {...props} isStreaming activeTurnId={activeTurnId} />,
    );

    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Copy"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Fork"]')).toHaveLength(1);

    rerender(<ThreadMessages {...props} isStreaming={false} activeTurnId={null} />);

    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Copy"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Fork"]')).toHaveLength(2);
  });

  it("keeps active turn actions hidden across guidance and failed user rows", () => {
    const activeTurnId = "turn-active";
    const messages: UIMessage[] = [
      { id: "old-user", role: "user", content: "old question", turnId: "turn-old", createdAt: 1 },
      { id: "old", role: "assistant", content: "old answer", turnId: "turn-old", createdAt: 2 },
      { id: "active-user", role: "user", content: "new question", turnId: activeTurnId, createdAt: 3 },
      { id: "live", role: "assistant", content: "live slice", createdAt: 4 },
      { id: "guide", role: "user", content: "focus", turnId: "turn-guide", createdAt: 5 },
      {
        id: "failed",
        role: "user",
        content: "retry",
        turnId: "turn-failed",
        deliveryStatus: "failed",
        createdAt: 6,
      },
    ];
    const { container } = render(
      <ThreadMessages
        messages={messages}
        isStreaming
        activeTurnId={activeTurnId}
        onForkFromMessage={vi.fn()}
      />,
    );

    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Copy"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Fork"]')).toHaveLength(1);
  });

  it("only hides the active assistant-only automation turn", () => {
    const { container } = render(
      <ThreadMessages
        messages={[
          { id: "old", role: "assistant", content: "old answer", turnId: "turn-old", createdAt: 1 },
          {
            id: "automation",
            role: "assistant",
            content: "automation result",
            turnId: "turn-automation",
            createdAt: 2,
          },
        ]}
        isStreaming
        activeTurnId="turn-automation"
        onForkFromMessage={vi.fn()}
      />,
    );

    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Copy"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Fork"]')).toHaveLength(0);
  });

  it("falls back to the latest user boundary for untagged active slices", () => {
    const { container } = render(
      <ThreadMessages
        messages={[
          { id: "user", role: "user", content: "question", createdAt: 1 },
          { id: "live", role: "assistant", content: "live slice", createdAt: 2 },
        ]}
        isStreaming
        activeTurnId="turn-active"
        onForkFromMessage={vi.fn()}
      />,
    );

    expect(container.querySelector('[data-assistant-footer] [aria-label="Copy"]'))
      .not.toBeInTheDocument();
    expect(container.querySelector('[data-assistant-footer] [aria-label="Fork"]'))
      .not.toBeInTheDocument();
  });

  it("falls back to the latest user boundary while the active turn id is pending", () => {
    const { container } = render(
      <ThreadMessages
        messages={[
          { id: "old-user", role: "user", content: "old question", turnId: "old", createdAt: 1 },
          { id: "old", role: "assistant", content: "old answer", turnId: "old", createdAt: 2 },
          { id: "new-user", role: "user", content: "new question", turnId: "new", createdAt: 3 },
          { id: "live", role: "assistant", content: "live slice", turnId: "new", createdAt: 4 },
        ]}
        isStreaming
        activeTurnId={null}
        onForkFromMessage={vi.fn()}
      />,
    );

    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Copy"]'))
      .toHaveLength(1);
    expect(container.querySelectorAll('[data-assistant-footer] [aria-label="Fork"]'))
      .toHaveLength(1);
  });

  it("projects adjacent assistant text slices into one answer", () => {
    const messages: UIMessage[] = [
      { id: "a1", role: "assistant", content: "part one", createdAt: 1 },
      { id: "a2", role: "assistant", content: "part two", createdAt: 2 },
    ];
    render(<ThreadMessages messages={messages} isStreaming={false} />);
    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(1);
    expect(screen.getByText("part one")).toBeInTheDocument();
    expect(screen.getByText("part two")).toBeInTheDocument();
  });

  it("does not count failed optimistic messages in assistant fork indices", () => {
    const onForkFromMessage = vi.fn();
    const messages: UIMessage[] = [
      { id: "u1", role: "user", content: "one", createdAt: 1 },
      { id: "a1", role: "assistant", content: "answer one", createdAt: 2 },
      {
        id: "u-failed",
        role: "user",
        content: "not persisted",
        deliveryStatus: "failed",
        createdAt: 3,
      },
      { id: "u2", role: "user", content: "two", createdAt: 4 },
      { id: "a2", role: "assistant", content: "answer two", createdAt: 5 },
    ];

    render(
      <ThreadMessages
        messages={messages}
        isStreaming={false}
        onForkFromMessage={onForkFromMessage}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Fork" }).at(-1)!);
    expect(onForkFromMessage).toHaveBeenCalledWith(2);
  });

  it("uses turn ids as activity grouping boundaries when available", () => {
    const units = buildDisplayUnits([
      { id: "u1", role: "user", content: "one", turnId: "turn-1", createdAt: 1 },
      { id: "a1", role: "assistant", content: "answer one", turnId: "turn-1", createdAt: 2 },
      {
        id: "t2",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        turnId: "turn-2",
        createdAt: 3,
      },
      { id: "a2", role: "assistant", content: "answer two", turnId: "turn-2", createdAt: 4 },
    ]);

    expect(units.map((unit) => unit.type === "message" ? unit.message.id : "activity")).toEqual([
      "u1",
      "a1",
      "activity",
      "a2",
    ]);
  });

  it("computes final assistant fork flags with user-boundary semantics", () => {
    const units = buildDisplayUnits([
      { id: "u1", role: "user", content: "one", createdAt: 1 },
      { id: "a1", role: "assistant", content: "draft", createdAt: 2 },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "tool()",
        traces: ["tool()"],
        createdAt: 3,
      },
      { id: "a2", role: "assistant", content: "final", createdAt: 4 },
      { id: "u2", role: "user", content: "two", createdAt: 5 },
      { id: "a3", role: "assistant", content: "next", createdAt: 6 },
    ]);

    const flags = assistantForkFlags(units);
    const assistantFlags = units
      .map((unit, index) =>
        unit.type === "message" && unit.message.role === "assistant"
          ? [unit.message.id, flags[index]]
          : null,
      )
      .filter(Boolean);

    expect(assistantFlags).toEqual([
      ["a1", false],
      ["a2", true],
      ["a3", true],
    ]);
  });

  it("keeps compaction notices out of assistant fork selection", () => {
    const units = buildDisplayUnits([
      { id: "u1", role: "user", content: "one", createdAt: 1 },
      { id: "a1", role: "assistant", content: "answer", createdAt: 2 },
      {
        id: "compaction-1",
        role: "assistant",
        content: "",
        kind: "compaction",
        createdAt: 3,
        compaction: {
          id: "compact-1",
          phase: "succeeded",
        },
      },
    ]);

    const flags = assistantForkFlags(units);
    expect(units.map((unit, index) => [
      unit.type === "message" ? unit.message.id : "activity",
      flags[index],
    ])).toEqual([
      ["u1", true],
      ["a1", true],
      ["compaction-1", false],
    ]);
  });
});
