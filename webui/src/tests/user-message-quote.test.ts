import { describe, expect, it } from "vitest";

import {
  formatQuotedUserMessage,
  parseQuotedUserMessage,
} from "@/lib/user-message-quote";

describe("user message quotes", () => {
  it("round-trips multiline quoted context through the message body", () => {
    const content = formatQuotedUserMessage(
      "What does this mean?",
      "first quoted line\n\nsecond quoted line",
    );

    expect(content).toBe(
      "> [!QUOTE]\n> first quoted line\n>\n> second quoted line\n\nWhat does this mean?",
    );
    expect(parseQuotedUserMessage(content)).toEqual({
      quotedContext: "first quoted line\n\nsecond quoted line",
      content: "What does this mean?",
    });
  });

  it("leaves ordinary messages and manual blockquotes unchanged", () => {
    const manualBlockquote = "> manually typed quote\n\nordinary message";

    expect(parseQuotedUserMessage(manualBlockquote)).toEqual({
      quotedContext: null,
      content: manualBlockquote,
    });
  });

  it("does not place quoted context ahead of slash commands", () => {
    expect(formatQuotedUserMessage("/model", "selected answer excerpt")).toBe("/model");
  });
});
