import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

/** Only successful create activity has a dedicated task surface. */
export function subagentCreateCallId(event: ToolProgressEvent): string | null {
  if (event.name !== "subagent" || !event.call_id || (event.phase !== "start" && event.phase !== "end")
    || event.error != null) return null;
  let args = event.arguments;
  if (typeof args === "string") {
    try { args = JSON.parse(args); } catch { return null; }
  }
  return args && typeof args === "object" && !Array.isArray(args)
    && (args as Record<string, unknown>).action === "create" ? event.call_id : null;
}

/** Strip only redundant create traces from a display copy; null means no visible activity remains. */
export function withoutSubagentCreateActivity(message: UIMessage): UIMessage | null {
  if (message.kind !== "trace" || !message.toolEvents?.some(subagentCreateCallId)) return message;
  const hidden = message.toolEvents.filter(subagentCreateCallId);
  const remaining = message.toolEvents.filter((event) => !subagentCreateCallId(event));
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
