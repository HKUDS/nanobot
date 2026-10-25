import { projectWebuiThreadMessages } from "./thread-display-projection";
import type { LoadedThreadMessages } from "./thread-message-cache";
import type { UIMessage } from "./types";

// Message objects and arrays are immutable; eviction also releases these weak entries.
const visibleMessages = new WeakMap<UIMessage[], UIMessage[]>();
const foldedContent = new WeakMap<UIMessage, string>();

function excerpt(text: string, folded: string, index: number): string {
  if (text.length !== folded.length) {
    let offset = 0;
    let original = 0;
    for (const char of text) {
      if (offset >= index) break;
      offset += char.toLowerCase().length;
      original += char.length;
    }
    index = original;
  }
  const start = Math.max(0, index - 48);
  const end = Math.min(text.length, Math.max(index + 112, start + 160));
  return `${start ? "…" : ""}${text.slice(start, end).replace(/\s+/g, " ").trim()}${end < text.length ? "…" : ""}`;
}

/** Find a literal substring in received user/answer text, never load history. */
export function findLoadedMessagePreview(groups: LoadedThreadMessages, query: string): string | undefined {
  for (const group of groups) {
    let visible = visibleMessages.get(group);
    if (!visible) {
      visible = projectWebuiThreadMessages(group);
      visibleMessages.set(group, visible);
    }
    for (let index = visible.length - 1; index >= 0; index--) {
      const message = visible[index];
      if ((message.role !== "user" && message.role !== "assistant")
        || (message.kind && message.kind !== "message") || message.activityKind) continue;
      let folded = foldedContent.get(message);
      if (folded === undefined) {
        folded = message.content.toLowerCase();
        foldedContent.set(message, folded);
      }
      const match = folded.indexOf(query);
      if (match >= 0) return excerpt(message.content, folded, match);
    }
  }
  return undefined;
}
