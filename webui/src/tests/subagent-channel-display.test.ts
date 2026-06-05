import { describe, expect, it } from "vitest";

import { scrubSubagentAnnounceBody, scrubSubagentUiMessages } from "@/lib/subagent-channel-display";
import type { UIMessage } from "@/lib/types";

describe("subagent-channel-display", () => {
  it("strips Task and Summarize tail", () => {
    const raw = `[Subagent 'A' failed]

Task: do thing

Result:
oops

Summarize this naturally for the user.`;
    expect(scrubSubagentAnnounceBody(raw)).toBe("[Subagent 'A' failed]\n\noops");
  });

  it("handles CRLF", () => {
    const raw =
      "[Subagent 'B' failed]\r\n\r\nTask: t\r\n\r\nResult:\r\nok\r\n\r\nSummarize this naturally";
    expect(scrubSubagentAnnounceBody(raw)).toContain("ok");
    expect(scrubSubagentAnnounceBody(raw)).not.toContain("Task:");
  });

  it("scrubs matching assistant rows", () => {
    const messages: UIMessage[] = [
      { id: "1", role: "user", content: "hi", createdAt: 1 },
      {
        id: "2",
        role: "assistant",
        content:
          "[Subagent 'C' failed]\n\nTask: long\n\nResult:\nshort\n\nSummarize this naturally",
        createdAt: 2,
      },
    ];
    const out = scrubSubagentUiMessages(messages);
    expect(out[0]).toBe(messages[0]);
    expect(out[1].content).toBe("[Subagent 'C' failed]\n\nshort");
  });
});
