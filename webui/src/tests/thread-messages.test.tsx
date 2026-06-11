import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
    assistantCopyFlags,
    buildDisplayUnits,
    ThreadMessages,
} from "@/components/thread/ThreadMessages";
import type { UIMessage } from "@/lib/types";

describe("ThreadMessages", () => {
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
      { id: "a1", role: "assistant", content: "answer", createdAt: 2 },
      { id: "u2", role: "user", content: "branch prompt", createdAt: 3 },
    ];

    render(
      <ThreadMessages
        messages={messages}
        forkBoundaryMessageCount={2}
      />,
    );

    expect(screen.getByText("Forked from history")).toBeInTheDocument();
  });

  it("keeps file edits as their own activity row inside a turn", () => {
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

    expect(units).toHaveLength(3);
    expect(units.map((unit) => unit.type)).toEqual(["activity", "activity", "activity"]);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual(["r1"]);
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual(["t1"]);
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual(["r2"]);
  });

  it("keeps ordinary tool activity in one Thought block across segment ids", () => {
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

  it("moves orphan trailing activity before the completed assistant answer", () => {
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
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual(["r1"]);
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual(["t1"]);
    expect(units[2]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "Let me search the latest data.",
      },
    });
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

    expect(screen.getByLabelText(/edited foo\.txt/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/editing foo\.txt/i)).not.toBeInTheDocument();
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
    expect(screen.getByText("Thought for 9s")).toBeInTheDocument();
    expect(screen.getByText("final answer")).toBeInTheDocument();
  });

  it("keeps late activity after the live assistant answer while streaming", () => {
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

    const units = buildDisplayUnits(messages, true);

    expect(units).toHaveLength(3);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual(["t0"]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "partial answer",
      },
    });
    expect(units[2].type === "activity" ? units[2].messages.map((m) => m.id) : []).toEqual(["t1"]);

    render(<ThreadMessages messages={messages} isStreaming />);

    const answer = screen.getByText("partial answer");
    const liveActivity = screen.getByRole("button", { name: /working/i });
    expect(answer.compareDocumentPosition(liveActivity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("moves late activity before a completed assistant answer", () => {
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
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual(["t1"]);
    expect(units[2]).toMatchObject({
      type: "message",
      message: {
        id: "a1",
        content: "Hong Kong is hot today.",
      },
    });

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    const answer = screen.getByText("Hong Kong is hot today.");
    const laterActivity = screen.getAllByText(/thought/i).at(-1);
    expect(laterActivity).toBeTruthy();
    expect(laterActivity!.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not leave a completed web-search thought below the final answer", () => {
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

    const thought = screen.getAllByText(/thought/i).at(-1);
    const answer = screen.getByText("知道，IEM Cologne Major 2026 今天开打了。");
    expect(thought).toBeTruthy();
    expect(thought!.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("normalizes completed prior turns while the next user turn is streaming", () => {
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

    const units = buildDisplayUnits(messages, true);

    expect(units).toHaveLength(4);
    expect(units[0].type === "activity" ? units[0].messages.map((m) => m.id) : []).toEqual([
      "thought",
    ]);
    expect(units[1].type === "activity" ? units[1].messages.map((m) => m.id) : []).toEqual([
      "web",
    ]);
    expect(units[2]).toMatchObject({
      type: "message",
      message: { id: "answer" },
    });
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

    const units = buildDisplayUnits(messages, true);

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

    expect(screen.getByText("Thought for 15s")).toBeInTheDocument();
    expect(screen.queryByText("Thought for 0s")).not.toBeInTheDocument();
  });

  it("shows copy only on the last assistant slice before the next user turn", () => {
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

    render(<ThreadMessages messages={messages} isStreaming={false} />);

    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(1);
    expect(screen.getByText("final reply")).toBeInTheDocument();
  });

  it("shows copy only on the second assistant when two text slices appear before user", () => {
    const messages: UIMessage[] = [
      { id: "a1", role: "assistant", content: "part one", createdAt: 1 },
      { id: "a2", role: "assistant", content: "part two", createdAt: 2 },
    ];
    render(<ThreadMessages messages={messages} isStreaming={false} />);
    expect(screen.getAllByRole("button", { name: "Copy" })).toHaveLength(1);
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

  it("computes final assistant copy flags with user-boundary semantics", () => {
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

    const flags = assistantCopyFlags(units);
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
});
