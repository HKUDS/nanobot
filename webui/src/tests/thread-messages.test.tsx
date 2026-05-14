import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import type { UIMessage } from "@/lib/types";

describe("ThreadMessages", () => {
  it("uses compact spacing between consecutive auxiliary rows", () => {
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

    const { container } = render(<ThreadMessages messages={messages} />);
    const rows = Array.from(container.firstElementChild?.children ?? []);

    expect(rows[0]).not.toHaveClass("mt-2", "mt-5");
    expect(rows[1]).toHaveClass("mt-2");
    expect(rows[2]).toHaveClass("mt-2");
    expect(rows[3]).toHaveClass("mt-5");
  });
});
