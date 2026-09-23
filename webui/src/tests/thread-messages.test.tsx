import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function openAssistantBlockMenu(root: ParentNode = document): HTMLElement {
  const row = root.querySelector("[data-assistant-message]")?.closest<HTMLElement>("[data-thread-display-unit]");
  expect(row).toBeTruthy();
  return openMessageBlockMenu(row!).trigger;
}

function assistantActionCounts(root: ParentNode = document) {
  const counts = { copy: 0, fork: 0 };
  for (const body of root.querySelectorAll("[data-assistant-message]")) {
    const row = body.closest<HTMLElement>("[data-thread-display-unit]")!;
    if (!row.querySelector("[data-message-block-menu-trigger]")) continue;
    const { menu } = openMessageBlockMenu(row);
    counts.copy += within(menu).queryAllByRole("button", { name: "Copy", exact: true }).length;
    counts.fork += within(menu).queryAllByRole("button", { name: "Fork", exact: true }).length;
    fireEvent.keyDown(menu, { key: "Escape" });
  }
  return counts;
}

function openMessageBlockMenu(root: ParentNode): {
  trigger: HTMLElement;
  menu: HTMLElement;
} {
  const trigger = root.querySelector<HTMLElement>("[data-message-block-menu-trigger]");
  expect(trigger).not.toBeNull();
  if (trigger?.getAttribute("aria-expanded") === "false") {
    fireEvent.click(trigger);
  }
  const menu = document.querySelector<HTMLElement>(
    '[data-message-block-menu][data-state="open"]',
  );
  expect(menu).not.toBeNull();
  return { trigger: trigger!, menu: menu! };
}

describe("ThreadMessages", () => {
  it.each([0, -13_000, -14_000, -15_000, 15_000])(
    "keeps the optimistic timer through acknowledgement and output with %i ms server clock skew",
    (clockSkewMs) => {
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
        createdAt: now,
      };
      const { rerender } = render(
        <ThreadMessages
          messages={[prompt]}
          isStreaming
          activeTurnId="turn-optimistic"
        />,
      );

      expect(screen.getByRole("status", { name: "Working for 0s" })).toBeInTheDocument();

      rerender(
        <ThreadMessages
          messages={[{ ...prompt, deliveryStatus: "accepted" }]}
          isStreaming
          activeTurnId="turn-optimistic"
          runStartedAt={(now + clockSkewMs) / 1000}
        />,
      );
      expect(screen.getByRole("status", { name: "Working for 0s" })).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(1000); });

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
          runStartedAt={(now + clockSkewMs) / 1000}
        />,
      );

      expect(screen.getByRole("button", { name: /^Working for 1s/ })).toBeInTheDocument();
    },
  );

  it("restores pending progress from the original prompt when guidance arrives", () => {
    vi.useFakeTimers();
    const now = 1_800_000_000_000;
    vi.setSystemTime(now);
    render(
      <ThreadMessages
        messages={[
          {
            id: "original", role: "user", content: "research this",
            turnId: "original-turn", createdAt: now - 30_000,
          },
          {
            id: "guidance", role: "user", content: "also check this",
            turnId: "guidance-turn", createdAt: now,
          },
        ]}
        isStreaming
        activeTurnId="original-turn"
        runStartedAt={(now - 43_000) / 1000}
      />,
    );
    expect(screen.getByRole("status", { name: "Working for 30s" })).toBeInTheDocument();
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

  it("recycles offscreen historical content while preserving its measured space", () => {
    let notify: (entries: Array<{ isIntersecting: boolean }>) => void = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: typeof notify) { notify = callback; }
      observe() {}
      disconnect() {}
    });
    const view = render(<ThreadMessages messages={[
      { id: "u1", role: "user", content: "old question", createdAt: 1 },
      { id: "a1", role: "assistant", content: "historical answer", createdAt: 2 },
      { id: "u2", role: "user", content: "latest question", createdAt: 3 },
    ]} isStreaming={false} />);
    const unit = screen.getByText("historical answer").closest<HTMLElement>("[data-thread-display-unit]")!;
    vi.spyOn(unit, "getBoundingClientRect").mockReturnValue({ height: 240 } as DOMRect);
    act(() => notify([{ isIntersecting: false }]));
    expect(unit.style.height).toBe("240px");
    expect(unit.childElementCount).toBe(0);
    act(() => notify([{ isIntersecting: true }]));
    expect(screen.getByText("historical answer")).toBeVisible();
    expect(view.container).toHaveTextContent("old question");
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
    const firstRow = firstAnswer.closest<HTMLElement>("[data-thread-display-unit]")!;
    const finalRow = finalAnswer.closest<HTMLElement>("[data-thread-display-unit]")!;
    const firstActions = firstRow.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!;
    const finalActions = finalRow.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!;
    expect(firstRow).toContainElement(firstActions);
    expect(finalRow).toContainElement(finalActions);
    expect(firstActions).not.toBe(finalActions);
    expect(firstRow).toHaveClass("message-context-hit-area");
    expect(finalRow).toHaveClass("message-context-hit-area");
    expect(finalActions).toHaveClass("absolute", "-start-[var(--message-block-trigger-offset)]", "top-0");
    expect(finalActions.querySelector("[data-message-block-menu-highlight]")).toHaveClass(
      "h-4",
      "w-7",
      "rounded-full",
    );
    expect(screen.queryByRole("button", { name: /worked/i })).not.toBeInTheDocument();
    fireEvent.click(finalActions);
    const completedActivity = screen.getByRole("button", { name: /worked/i });
    expect(completedActivity).toHaveClass("min-h-[var(--message-block-control-size)]");
    expect(completedActivity).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelectorAll("[data-block-context-rail]")).toHaveLength(0);
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

    const ok = screen.getByText("ok");
    const final = screen.getByText("finished");
    expect(ok.compareDocumentPosition(final) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    const okRow = ok.closest<HTMLElement>("[data-thread-display-unit]")!;
    const finalRow = final.closest<HTMLElement>("[data-thread-display-unit]")!;
    openMessageBlockMenu(okRow);
    expect(screen.getByRole("button", { name: /^worked/i })).toBeInTheDocument();
    const { menu } = openMessageBlockMenu(finalRow);
    const finalActivity = menu.querySelector<HTMLElement>("[data-message-block-activity-action]")!;
    expect(finalActivity).toBeInTheDocument();
    fireEvent.click(finalActivity);
    expect(screen.getByTestId("agent-activity-content")).toHaveTextContent("Completed First");
    expect(screen.getByTestId("agent-activity-content")).toHaveTextContent("Completed Second");
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

  it("keeps one completed activity row above the final answer", async () => {
    const messages: UIMessage[] = [
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "thinking",
        reasoningStreaming: false,
        isStreaming: true,
        createdAt: 1_000,
      },
      {
        id: "t1",
        role: "tool",
        kind: "trace",
        content: "search()",
        traces: ["search()"],
        createdAt: 2_000,
      },
      {
        id: "r2",
        role: "assistant",
        content: "",
        reasoning: "more thinking",
        reasoningStreaming: false,
        isStreaming: true,
        createdAt: 3_000,
      },
      {
        id: "a1",
        role: "assistant",
        content: "final answer",
        latencyMs: 16_000,
        createdAt: 4_000,
      },
    ];

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    const rows = Array.from(container.firstElementChild?.children ?? []);

    expect(rows).toHaveLength(2);
    expect(rows[0]).not.toHaveClass("mt-2", "mt-4", "mt-5");
    expect(rows[1]).not.toHaveClass("mt-4");
    const answerRow = screen.getByText("final answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const { trigger, menu } = openMessageBlockMenu(answerRow);
    const disclosure = screen.getByRole("button", { name: "Worked for 16s" });
    expect(menu).toHaveFocus();
    expect(menu.querySelector("[data-message-block-copy-action]")).not.toHaveFocus();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(disclosure).toHaveAttribute("aria-controls");
    expect(disclosure).toHaveAttribute("data-message-block-activity-action", "true");
    expect(disclosure).toHaveClass("min-h-[var(--message-block-control-size)]", "group", "hover:text-foreground");
    expect(disclosure).not.toHaveClass("hover:bg-muted/60");
    expect(menu.querySelector("[data-message-block-copy-action]")).toHaveClass(
      "rounded-control",
      "h-[var(--message-block-control-size)]",
      "w-[var(--message-block-action-width)]",
    );
    expect(menu.querySelector("[data-message-block-copy-action]")).not.toHaveClass("touch-target");
    expect(disclosure.querySelector("[data-message-block-activity-icon]")).toHaveClass(
      "h-[var(--message-block-control-size)]",
      "w-[var(--message-block-action-width)]",
      "rounded-control",
      "group-hover:bg-muted/70",
    );
    expect(disclosure.querySelector("svg")).toBeInTheDocument();
    const toolbar = menu.querySelector("[data-message-block-toolbar]");
    expect(toolbar).toHaveClass("flex", "flex-wrap", "items-center");
    expect(toolbar).not.toHaveClass("flex-col");
    expect(toolbar).toContainElement(menu.querySelector("[data-message-block-copy-action]"));
    expect(toolbar).toContainElement(disclosure);
    const timestamp = menu.querySelector<HTMLElement>("[data-message-timestamp]")!;
    expect(timestamp).toBeInTheDocument();
    expect(timestamp).toHaveClass("min-h-[var(--message-block-control-size)]");
    expect(timestamp.parentElement).toHaveClass("border-t", "text-muted-foreground/45");
    expect(toolbar).not.toContainElement(timestamp);
    expect(timestamp).not.toHaveAttribute("tabindex");
    expect(timestamp.querySelector("svg")).not.toBeInTheDocument();
    expect(disclosure.compareDocumentPosition(timestamp) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(menu).toHaveClass("w-max", "max-w-64", "bg-popover", "rounded-floating", "overflow-y-auto");
    expect(menu).not.toHaveClass("min-w-[8.5rem]", "bg-popover/95", "rounded-xl");
    const menuButtons = Array.from(menu.querySelectorAll("button"));
    expect(menuButtons.length).toBeGreaterThan(1);
    for (const button of menuButtons) {
      expect(button.className).toMatch(/(?:min-)?h-\[var\(--message-block-control-size\)\]/);
    }
    expect(rows[0].compareDocumentPosition(rows[1]) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();

    fireEvent.click(disclosure);

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(answerRow.querySelector("[data-contextual-activity]")?.parentElement?.parentElement)
      .toHaveClass("mb-2");
    expect(screen.getByTestId("agent-activity-content")).toBeInTheDocument();
    const collapse = screen.getByRole("button", { name: /Collapse activity details/ });
    expect(collapse).toHaveAttribute("data-contextual-activity-collapse", "true");
    expect(collapse.querySelectorAll("svg")).toHaveLength(1);
    const guide = answerRow.querySelector("[data-contextual-activity-guide]");
    expect(guide).toBeInTheDocument();
    expect(guide).toHaveClass("start-[13px]");
    expect(screen.getByTestId("agent-activity-content")).toHaveClass("ps-6");
    await waitFor(() => expect(collapse).toHaveFocus());
    fireEvent.click(collapse);

    expect(answerRow.querySelector("[data-contextual-activity]")?.parentElement?.parentElement)
      .not.toHaveClass("mb-2");
    expect(screen.queryByTestId("agent-activity-content")).not.toBeInTheDocument();
    expect(answerRow.querySelector("[data-contextual-activity-guide]"))
      .not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("activates only the hovered visual message block within one logical turn", () => {
    const messages: UIMessage[] = [
      {
        id: "user",
        role: "user",
        content: "prompt",
        createdAt: 500,
      },
      {
        id: "tool-a",
        role: "tool",
        kind: "trace",
        content: "first command",
        traces: ["first command"],
        createdAt: 1_000,
      },
      {
        id: "answer-a",
        role: "assistant",
        content: "first answer",
        createdAt: 2_000,
      },
      {
        id: "tool-b",
        role: "tool",
        kind: "trace",
        content: "second command",
        traces: ["second command"],
        createdAt: 3_000,
      },
      {
        id: "answer-b",
        role: "assistant",
        content: "second answer",
        createdAt: 4_000,
      },
    ];

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    const activityA = container.querySelector<HTMLElement>(
      '[data-thread-display-unit="activity-tool-a"]',
    )!;
    const answerA = screen.getByText("first answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const activityB = container.querySelector<HTMLElement>(
      '[data-thread-display-unit="activity-tool-b"]',
    )!;
    const answerB = screen.getByText("second answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;

    expect(activityA).not.toHaveAttribute("data-message-context-block");
    expect(activityB).not.toHaveAttribute("data-message-context-block");
    expect(answerA.dataset.messageContextBlock).toBeTruthy();
    expect(answerB.dataset.messageContextBlock).toBeTruthy();
    expect(answerA.dataset.messageContextBlock)
      .not.toBe(answerB.dataset.messageContextBlock);
    expect(answerA.querySelector("[data-contextual-activity]")).toBeInTheDocument();
    expect(answerB.querySelector("[data-contextual-activity]")).toBeInTheDocument();
    expect(answerA).toHaveClass("message-context-hit-area", "relative");
    expect(answerB).toHaveClass("message-context-hit-area", "relative");

    fireEvent.pointerEnter(answerA, { pointerType: "mouse" });
    expect(answerA).toHaveAttribute("data-context-block-active", "true");
    expect(answerB).not.toHaveAttribute("data-context-block-active");

    fireEvent.pointerEnter(answerB, { pointerType: "mouse" });
    expect(answerA).not.toHaveAttribute("data-context-block-active");
    expect(answerB).toHaveAttribute("data-context-block-active", "true");

    const answerBTrigger = answerB.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!;
    expect(answerBTrigger).toHaveClass(
      "-start-[var(--message-block-trigger-offset)]",
      "h-[var(--message-block-control-size)]",
      "w-[var(--message-block-control-size)]",
    );
    fireEvent.pointerLeave(answerB, {
      pointerType: "mouse",
      relatedTarget: answerBTrigger,
    });
    expect(answerB).toHaveAttribute("data-context-block-active", "true");
    fireEvent.pointerLeave(answerB, { pointerType: "mouse" });
    expect(answerB).not.toHaveAttribute("data-context-block-active");

    fireEvent.focus(answerA.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!);
    expect(answerA).toHaveAttribute("data-context-block-active", "true");
    fireEvent.focus(answerBTrigger);
    expect(answerA).not.toHaveAttribute("data-context-block-active");
    expect(answerB).toHaveAttribute("data-context-block-active", "true");
  });

  it("uses one active visual block across user and assistant messages", () => {
    const messages: UIMessage[] = [
      { id: "user-a", role: "user", content: "first prompt", createdAt: 500 },
      { id: "answer-a", role: "assistant", content: "first answer", createdAt: 1_000 },
      { id: "user-b", role: "user", content: "second prompt", createdAt: 1_500 },
    ];

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    const userA = screen.getByText("first prompt")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const answerA = screen.getByText("first answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const userB = screen.getByText("second prompt")
      .closest<HTMLElement>("[data-thread-display-unit]")!;

    expect(userA.dataset.messageContextBlock).toBeTruthy();
    expect(userB.dataset.messageContextBlock).toBeTruthy();
    expect(userA.dataset.messageContextBlock).not.toBe(answerA.dataset.messageContextBlock);
    expect(userB.dataset.messageContextBlock).not.toBe(answerA.dataset.messageContextBlock);
    expect(userA.querySelector("[data-message-block-menu-trigger]")).toBeInTheDocument();
    expect(userB.querySelector("[data-message-block-menu-trigger]")).toBeInTheDocument();

    fireEvent.pointerEnter(userA, { pointerType: "mouse" });
    expect(userA).toHaveAttribute("data-context-block-active", "true");
    expect(answerA).not.toHaveAttribute("data-context-block-active");

    fireEvent.pointerEnter(answerA, { pointerType: "mouse" });
    expect(userA).not.toHaveAttribute("data-context-block-active");
    expect(answerA).toHaveAttribute("data-context-block-active", "true");

    fireEvent.pointerEnter(userB, { pointerType: "mouse" });
    expect(answerA).not.toHaveAttribute("data-context-block-active");
    expect(userB).toHaveAttribute("data-context-block-active", "true");

    const { menu: userMenu } = openMessageBlockMenu(userA);
    expect(userMenu.querySelector("[data-message-block-copy-action]")).toBeInTheDocument();
    expect(userMenu.querySelector("[data-message-block-fork-action]")).not.toBeInTheDocument();
    fireEvent.focus(userA.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!);
    expect(userA).toHaveAttribute("data-context-block-active", "true");
    expect(userB).not.toHaveAttribute("data-context-block-active");
  });

  it("closes an open block menu after the pointer leaves its block and panel", async () => {
    const messages: UIMessage[] = [
      { id: "user-a", role: "user", content: "first prompt", createdAt: 500 },
      { id: "answer-a", role: "assistant", content: "first answer", createdAt: 1_000 },
      { id: "user-b", role: "user", content: "second prompt", createdAt: 1_500 },
    ];

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    const userA = screen.getByText("first prompt")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const userB = screen.getByText("second prompt")
      .closest<HTMLElement>("[data-thread-display-unit]")!;

    fireEvent.pointerEnter(userA, { pointerType: "mouse" });
    const { menu } = openMessageBlockMenu(userA);
    expect(menu).toHaveAttribute(
      "data-message-context-menu-block",
      userA.dataset.messageContextBlock,
    );

    fireEvent.pointerLeave(userA, {
      pointerType: "mouse",
      relatedTarget: menu,
    });
    expect(menu).toHaveAttribute("data-state", "open");
    expect(userA).toHaveAttribute("data-context-block-active", "true");

    fireEvent.pointerLeave(menu, {
      pointerType: "mouse",
      relatedTarget: userB,
    });
    await waitFor(() => {
      expect(document.querySelector('[data-message-block-menu][data-state="open"]'))
        .not.toBeInTheDocument();
    });
    expect(userA).not.toHaveAttribute("data-context-block-active");
    expect(userB).toHaveAttribute("data-context-block-active", "true");

    fireEvent.pointerEnter(userA, { pointerType: "mouse" });
    openMessageBlockMenu(userA);
    fireEvent.pointerEnter(userB, { pointerType: "mouse" });
    await waitFor(() => {
      expect(document.querySelector('[data-message-block-menu][data-state="open"]'))
        .not.toBeInTheDocument();
    });
    expect(userB).toHaveAttribute("data-context-block-active", "true");
  });

  it("clears completed block controls when the pointer enters an ungrouped message", () => {
    const messages: UIMessage[] = [
      { id: "user-a", role: "user", content: "first prompt", createdAt: 500 },
      {
        id: "tool-a",
        role: "tool",
        kind: "trace",
        content: "first command",
        traces: ["first command"],
        createdAt: 1_000,
      },
      { id: "answer-a", role: "assistant", content: "first answer", createdAt: 2_000 },
      { id: "user-b", role: "user", content: "current prompt", createdAt: 3_000 },
      {
        id: "answer-b",
        role: "assistant",
        content: "current answer",
        isStreaming: true,
        createdAt: 4_000,
      },
    ];

    render(<ThreadMessages messages={messages} isStreaming activeTurnId={null} />);
    const completedAnswer = screen.getByText("first answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const currentAnswer = screen.getByText("current answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;

    fireEvent.pointerEnter(completedAnswer, { pointerType: "mouse" });
    expect(completedAnswer).toHaveAttribute("data-context-block-active", "true");

    fireEvent.pointerEnter(currentAnswer, { pointerType: "mouse" });
    expect(completedAnswer).not.toHaveAttribute("data-context-block-active");
  });

  it("keeps only the last tapped message block controls active on touch", () => {
    const messages: UIMessage[] = [
      { id: "user-a", role: "user", content: "first prompt", createdAt: 500 },
      { id: "answer-a", role: "assistant", content: "first answer", createdAt: 1_000 },
      { id: "user-b", role: "user", content: "second prompt", createdAt: 1_500 },
      { id: "answer-b", role: "assistant", content: "second answer", createdAt: 2_000 },
    ];

    render(<ThreadMessages messages={messages} isStreaming={false} />);
    const answerA = screen.getByText("first answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const answerB = screen.getByText("second answer")
      .closest<HTMLElement>("[data-thread-display-unit]")!;

    fireEvent.pointerDown(answerA, { pointerType: "touch" });
    fireEvent.pointerLeave(answerA, { pointerType: "touch" });
    expect(answerA).toHaveAttribute("data-context-block-active", "true");

    fireEvent.pointerDown(answerB, { pointerType: "touch" });
    expect(answerA).not.toHaveAttribute("data-context-block-active");
    expect(answerB).toHaveAttribute("data-context-block-active", "true");
  });

  it.each(["mouse", "touch"])("preserves the %s block when previous controls lose focus", (pointerType) => {
    render(<ThreadMessages messages={[
      { id: "user", role: "user", content: "prompt", createdAt: 1 },
      { id: "answer", role: "assistant", content: "answer", createdAt: 2 },
    ]} />);
    const user = screen.getByText("prompt").closest<HTMLElement>("[data-thread-display-unit]")!;
    const answer = screen.getByText("answer").closest<HTMLElement>("[data-thread-display-unit]")!;
    const trigger = user.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!;
    fireEvent.focus(trigger);
    if (pointerType === "touch") {
      openMessageBlockMenu(user);
      fireEvent.pointerDown(answer, { pointerType });
    } else {
      fireEvent.pointerEnter(answer, { pointerType });
      fireEvent.pointerDown(answer, { pointerType });
    }
    fireEvent.blur(trigger, { relatedTarget: document.body });

    expect(answer).toHaveAttribute("data-context-block-active", "true");
    expect(user).not.toHaveAttribute("data-context-block-active");
    expect(document.querySelector('[data-message-block-menu][data-state="open"]')).toBeNull();
  });

  it("closes the block menu with Escape from a focused copy action", async () => {
    render(<ThreadMessages messages={[
      { id: "answer", role: "assistant", content: "answer", createdAt: 2 },
    ]} />);
    const answer = screen.getByText("answer").closest<HTMLElement>("[data-thread-display-unit]")!;
    const { menu, trigger } = openMessageBlockMenu(answer);
    const copy = menu.querySelector<HTMLElement>("[data-message-block-copy-action]")!;
    act(() => copy.focus());
    expect(copy).toHaveFocus();
    fireEvent.keyDown(copy, { key: "Escape" });
    await waitFor(() => expect(menu).not.toBeInTheDocument());
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("clears keyboard context when focus leaves and no pointer owns a block", () => {
    render(<ThreadMessages messages={[
      { id: "answer", role: "assistant", content: "answer", createdAt: 2 },
    ]} />);
    const answer = screen.getByText("answer").closest<HTMLElement>("[data-thread-display-unit]")!;
    const trigger = answer.querySelector<HTMLElement>("[data-message-block-menu-trigger]")!;
    fireEvent.focus(trigger);
    expect(answer).toHaveAttribute("data-context-block-active", "true");
    fireEvent.blur(trigger, { relatedTarget: document.body });
    expect(answer).not.toHaveAttribute("data-context-block-active");
  });

  it.each(["cron", "local_trigger", "trigger"])("preserves %s provenance as static menu metadata", (kind) => {
    render(<ThreadMessages messages={[
      { id: "answer", role: "assistant", content: "automated answer", createdAt: 2,
        source: { kind, label: "Review schedule" } },
    ]} />);
    const answer = screen.getByText("automated answer").closest<HTMLElement>("[data-thread-display-unit]")!;
    const { menu } = openMessageBlockMenu(answer);
    const metadata = menu.querySelector<HTMLElement>("[data-message-block-metadata]")!;
    expect(metadata).toHaveTextContent("Triggered automatically · Review schedule");
    expect(metadata.querySelector("time[datetime]")).toBeInTheDocument();
    expect(metadata.querySelector("button, svg, [tabindex]")).toBeNull();
    expect(metadata).toBe(menu.querySelector("[data-message-block-menu-actions]")?.lastElementChild);
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

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    expect(screen.queryByRole("button", { name: /^thinking$/i })).not.toBeInTheDocument();
    openAssistantBlockMenu(container);
    const disclosure = screen.getByRole("button", { name: "Worked for 9s" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(disclosure);
    expect(screen.getByTestId("agent-activity-content")).toBeInTheDocument();
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

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    openAssistantBlockMenu(container);
    expect(screen.getByRole("button", { name: "Worked for 20s" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Worked for 3s" }))
      .not.toBeInTheDocument();
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

  it("summarizes late activity above the completed assistant answer", () => {
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
    openMessageBlockMenu(answer.closest<HTMLElement>("[data-thread-display-unit]")!);
    const laterActivity = screen.getAllByRole("button", { name: /worked/i }).at(-1);
    expect(laterActivity).toBeTruthy();
    expect(laterActivity).toHaveAttribute("data-message-block-activity-action", "true");
  });

  it("folds completed web-search activity into one row above the answer", () => {
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

    const answer = screen.getByText("知道，IEM Cologne Major 2026 今天开打了。");
    openMessageBlockMenu(answer.closest<HTMLElement>("[data-thread-display-unit]")!);
    const activities = screen.getAllByRole("button", { name: /worked/i });
    expect(activities).toHaveLength(1);
    expect(activities[0]).toHaveAttribute("data-message-block-activity-action", "true");
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

    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );

    openAssistantBlockMenu(container);
    expect(screen.getByRole("button", { name: "Worked for 15s" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Worked for 0s" }))
      .not.toBeInTheDocument();
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

    expect(assistantActionCounts(document)).toEqual({ copy: 2, fork: 1 });
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
    const ownerRow = screen.getByText("result.csv")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    openAssistantBlockMenu(ownerRow);
    expect(screen.getByRole("button", { name: "Worked" })).toBeInTheDocument();
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

    const firstAnswer = screen.getByText("first answer slice")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    const finalAnswer = screen.getByText("second answer slice")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    expect(firstAnswer.querySelector("[data-message-block-menu-trigger]"))
      .not.toBeInTheDocument();
    expect(finalAnswer.querySelector("[data-message-block-menu-trigger]"))
      .not.toBeInTheDocument();
    expect(assistantActionCounts(container)).toEqual({ copy: 1, fork: 1 });

    rerender(<ThreadMessages {...props} isStreaming={false} activeTurnId={null} />);

    expect(firstAnswer.querySelector("[data-message-block-menu-trigger]"))
      .toBeInTheDocument();
    expect(assistantActionCounts(container)).toEqual({ copy: 3, fork: 2 });
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

    expect(assistantActionCounts(container)).toEqual({ copy: 1, fork: 1 });
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

    expect(assistantActionCounts(container)).toEqual({ copy: 1, fork: 0 });
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

    expect(assistantActionCounts(container)).toEqual({ copy: 0, fork: 0 });
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

    expect(assistantActionCounts(container)).toEqual({ copy: 1, fork: 1 });
  });

  it("projects adjacent assistant text slices into one answer", () => {
    const messages: UIMessage[] = [
      { id: "a1", role: "assistant", content: "part one", createdAt: 1 },
      { id: "a2", role: "assistant", content: "part two", createdAt: 2 },
    ];
    const { container } = render(
      <ThreadMessages messages={messages} isStreaming={false} />,
    );
    expect(assistantActionCounts(container).copy).toBe(1);
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

    const answerRow = screen.getByText("answer two")
      .closest<HTMLElement>("[data-thread-display-unit]")!;
    openMessageBlockMenu(answerRow);
    fireEvent.click(document.querySelector("[data-message-block-fork-action]")!);
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
