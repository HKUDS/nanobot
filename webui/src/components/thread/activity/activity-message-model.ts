import {
  canonicalToolTrace,
  mergeToolProgressEvents,
  mergeToolProgressTraceLines,
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
  const calls = new Map<string, { latest: number; byTurn: Map<string, number> }>();

  for (const message of messages) {
    let targetIndex = -1;
    if (message.kind === "trace") {
      for (const event of message.toolEvents ?? []) {
        if (!event.call_id) continue;
        const call = calls.get(event.call_id);
        if (!call) continue;
        const index = message.turnId
          ? Math.max(call.byTurn.get(message.turnId) ?? -1, call.byTurn.get("") ?? -1)
          : call.latest;
        targetIndex = Math.max(targetIndex, index);
      }
      if (targetIndex < 0 && canMergeAdjacentProgress(normalized.at(-1), message)) {
        targetIndex = normalized.length - 1;
      }
    }
    if (targetIndex < 0) {
      targetIndex = normalized.length;
      normalized.push(message);
    } else {
      normalized[targetIndex] = mergeTraceMessages(normalized[targetIndex], message);
    }
    if (message.kind !== "trace") continue;
    // Merging preserves the target's turn. Legacy rows without a turn match any turn.
    const turn = normalized[targetIndex].turnId || "";
    for (const event of message.toolEvents ?? []) {
      if (!event.call_id) continue;
      let call = calls.get(event.call_id);
      if (!call) {
        call = { latest: targetIndex, byTurn: new Map() };
        calls.set(event.call_id, call);
      }
      call.latest = Math.max(call.latest, targetIndex);
      call.byTurn.set(turn, Math.max(call.byTurn.get(turn) ?? -1, targetIndex));
    }
  }

  return normalized;
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
  const toolEvents = mergeToolProgressEvents(previous.toolEvents, incoming.toolEvents ?? []);
  const traces = incoming.toolEvents?.length
    ? mergeToolProgressTraceLines(
        messageTraces(previous),
        previous.toolEvents,
        messageTraces(incoming),
        incoming.toolEvents ?? [],
      )
    : mergeUniqueToolTraceLines(messageTraces(previous), messageTraces(incoming)).traces;
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
