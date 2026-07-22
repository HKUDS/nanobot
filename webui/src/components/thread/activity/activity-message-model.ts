import {
  canonicalToolTrace,
  mergeToolProgressEvents,
  mergeUniqueToolTraceLines,
} from "@/lib/tool-traces";
import type { UIMediaAttachment, UIMessage } from "@/lib/types";

/**
 * Live tool progress is already folded into one trace message. Persisted
 * transcripts can contain the same progress as adjacent start/end rows, so
 * normalize both paths before rendering the activity timeline.
 */
export function coalesceActivityMessages(messages: UIMessage[]): UIMessage[] {
  const normalized: UIMessage[] = [];

  for (const message of messages) {
    const targetIndex = findMergeTarget(normalized, message);
    if (targetIndex < 0) {
      normalized.push(message);
      continue;
    }
    normalized[targetIndex] = mergeTraceMessages(normalized[targetIndex], message);
  }

  return normalized;
}

function findMergeTarget(messages: UIMessage[], incoming: UIMessage): number {
  if (incoming.kind !== "trace") return -1;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const previous = messages[index];
    if (previous.kind !== "trace") continue;
    if (hasSharedToolCall(previous, incoming) && sameTurn(previous, incoming)) return index;
  }

  const adjacentIndex = messages.length - 1;
  const adjacent = messages[adjacentIndex];
  return canMergeAdjacentProgress(adjacent, incoming) ? adjacentIndex : -1;
}

function canMergeAdjacentProgress(
  previous: UIMessage | undefined,
  incoming: UIMessage,
): previous is UIMessage {
  if (!previous || previous.kind !== "trace") return false;
  if (!sameTurn(previous, incoming)) return false;
  if (
    previous.activitySegmentId
    && incoming.activitySegmentId
    && previous.activitySegmentId === incoming.activitySegmentId
  ) {
    return true;
  }
  return hasSharedTrace(previous, incoming) && completesPreviousProgress(previous, incoming);
}

function mergeTraceMessages(previous: UIMessage, incoming: UIMessage): UIMessage {
  const traces = mergeUniqueToolTraceLines(messageTraces(previous), messageTraces(incoming)).traces;
  const toolEvents = mergeToolProgressEvents(previous.toolEvents, incoming.toolEvents ?? []);
  const fileEdits = [...(previous.fileEdits ?? []), ...(incoming.fileEdits ?? [])];
  const media = uniqueMedia([...(previous.media ?? []), ...(incoming.media ?? [])]);

  return {
    ...previous,
    content: traces[traces.length - 1] ?? incoming.content ?? previous.content,
    traces,
    ...(toolEvents.length ? { toolEvents } : { toolEvents: undefined }),
    ...(fileEdits.length ? { fileEdits } : { fileEdits: undefined }),
    ...(media.length ? { media } : { media: undefined }),
    isStreaming: incoming.isStreaming,
    turnPhase: incoming.turnPhase ?? previous.turnPhase,
    turnSeq: incoming.turnSeq ?? previous.turnSeq,
  };
}

function messageTraces(message: UIMessage): string[] {
  if (message.traces?.length) return message.traces;
  return message.content.trim() ? [message.content] : [];
}

function hasSharedToolCall(previous: UIMessage, incoming: UIMessage): boolean {
  const previousCallIds = new Set(
    (previous.toolEvents ?? []).map((event) => event.call_id).filter(Boolean),
  );
  return (incoming.toolEvents ?? []).some((event) => (
    !!event.call_id && previousCallIds.has(event.call_id)
  ));
}

function hasSharedTrace(previous: UIMessage, incoming: UIMessage): boolean {
  const previousTraces = new Set(messageTraces(previous).map(canonicalToolTrace));
  return messageTraces(incoming).some((trace) => previousTraces.has(canonicalToolTrace(trace)));
}

function completesPreviousProgress(previous: UIMessage, incoming: UIMessage): boolean {
  const previousPhases = new Set((previous.toolEvents ?? []).map((event) => event.phase));
  const incomingPhases = new Set((incoming.toolEvents ?? []).map((event) => event.phase));
  return previousPhases.has("start") && (incomingPhases.has("end") || incomingPhases.has("error"));
}

function sameTurn(previous: UIMessage, incoming: UIMessage): boolean {
  return !previous.turnId || !incoming.turnId || previous.turnId === incoming.turnId;
}

function uniqueMedia(media: UIMediaAttachment[]): UIMediaAttachment[] {
  const seen = new Set<string>();
  return media.filter((item) => {
    const key = `${item.kind}:${item.url ?? ""}:${item.name ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
