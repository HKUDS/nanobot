import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

/** Only successful create activity has a dedicated task surface. */
function isSubagentCreateActivity(event: ToolProgressEvent): boolean {
  if (event.name !== "subagent" || (event.phase !== "start" && event.phase !== "end")
    || event.error != null) return false;
  let args = event.arguments;
  if (typeof args === "string") {
    try { args = JSON.parse(args); } catch { return false; }
  }
  return args != null && typeof args === "object" && !Array.isArray(args)
    && (args as Record<string, unknown>).action === "create";
}

/** Strip only redundant create traces from a display copy; null means no visible activity remains. */
export function withoutSubagentCreateActivity(message: UIMessage): UIMessage | null {
  if (message.kind !== "trace" || !message.toolEvents?.some(isSubagentCreateActivity)) return message;
  const hidden = message.toolEvents.filter(isSubagentCreateActivity);
  const remaining = message.toolEvents.filter((event) => !isSubagentCreateActivity(event));
  const traceSet = (events: ToolProgressEvent[]) => new Set(events.map(formatToolCallTrace)
    .filter((line): line is string => line !== null).map(canonicalToolTrace));
  const hiddenLines = traceSet(hidden);
  const retainedLines = traceSet(remaining);
  const original = message.traces?.length ? message.traces : message.content ? [message.content] : [];
  const traces = original.filter((line) => !hiddenLines.has(canonicalToolTrace(line))
    || retainedLines.has(canonicalToolTrace(line)));
  if (!remaining.length && !traces.length && !message.fileEdits?.length && !message.traceDetail
    && !message.media?.length && !message.images?.length && !message.reasoning && !message.reasoningStreaming) return null;
  return { ...message, toolEvents: remaining.length ? remaining : undefined,
    traces, content: traces.at(-1) ?? "" };
}
