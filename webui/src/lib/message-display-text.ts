import { renderCommandResult } from "../../../packages/client-events/command-result";
import type { UIMessage } from "./types";

/** Body text shared by the transcript, clipboard, and loaded-message search. */
export function messageDisplayText(message: UIMessage, t: (key: string) => string, locale: string): string {
  if (message.commandResult !== undefined) {
    return renderCommandResult(message.commandResult, locale) ?? message.content;
  }
  if (message.renderAs !== "text" && message.role === "assistant") {
    if (message.compactReply === "empty") return t("thread.compaction.empty");
    if (message.compactReply === "failed") return t("thread.compaction.failed");
  }
  return message.content;
}
