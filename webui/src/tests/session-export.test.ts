import { describe, expect, it } from "vitest";

import {
  buildSessionMarkdown,
  sessionMarkdownFilename,
} from "@/lib/session-export";
import type { ChatSummary, UIMessage } from "@/lib/types";

const session: ChatSummary = {
  key: "websocket:chat-1",
  channel: "websocket",
  chatId: "chat-1",
  createdAt: "2026-06-01T10:00:00Z",
  updatedAt: "2026-06-01T10:05:00Z",
  title: "Export demo",
  preview: "",
};

describe("session-export", () => {
  it("exports conversational messages as markdown while preserving code blocks", () => {
    const messages: UIMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "Please keep this code:\n\n```ts\nconst value = 1;\n```",
        createdAt: Date.parse("2026-06-01T10:01:00Z"),
      },
      {
        id: "a1",
        role: "assistant",
        content: "Done.",
        createdAt: Date.parse("2026-06-01T10:02:00Z"),
      },
    ];

    const markdown = buildSessionMarkdown({
      session,
      title: "Export demo",
      messages,
      locale: "en",
    });

    expect(markdown).toContain("# Export demo");
    expect(markdown).toContain("- Session: `websocket:chat-1`");
    expect(markdown).toContain("## User");
    expect(markdown).toContain("```ts\nconst value = 1;\n```");
    expect(markdown).toContain("## Assistant");
    expect(markdown).toContain("Done.");
  });

  it("collapses trace, tool, and file edit activity into details", () => {
    const markdown = buildSessionMarkdown({
      session,
      title: "Activity demo",
      locale: "en",
      messages: [
        {
          id: "trace-1",
          role: "assistant",
          kind: "trace",
          content: "",
          createdAt: Date.parse("2026-06-01T10:02:00Z"),
          traces: ["Running shell command"],
          toolEvents: [{ name: "shell", phase: "end" }],
          fileEdits: [{
            call_id: "edit-1",
            tool: "edit",
            path: "src/app.ts",
            added: 2,
            deleted: 1,
            status: "done",
          }],
        },
      ],
    });

    expect(markdown).toContain("<details>");
    expect(markdown).toContain("<summary>Activity");
    expect(markdown).toContain("- Running shell command");
    expect(markdown).toContain("- shell (end)");
    expect(markdown).toContain("- edited src/app.ts, +2/-1");
    expect(markdown).toContain("</details>");
  });

  it("sanitizes exported filenames", () => {
    expect(sessionMarkdownFilename("Fix / chat: export?", "websocket:chat-1"))
      .toBe("fix-chat-export.md");
  });
});
