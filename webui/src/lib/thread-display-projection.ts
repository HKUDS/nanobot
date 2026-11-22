import { projectActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import { withoutSubagentCreateActivity } from "@/lib/subagent-create-activity";
import { isSystemCommandTurnId } from "@/lib/nanobot-client";
import { scrubSubagentUiMessages } from "@/lib/subagent-channel-display";
import type { UIMessage } from "@/lib/types";

interface PreparedMessage {
  message: UIMessage;
  hidden: boolean;
}

const preparedMessages = new WeakMap<UIMessage, PreparedMessage>();
const completionMessages = new WeakMap<UIMessage, { completedAt: number; message: UIMessage }>();

function prepareMessage(original: UIMessage): PreparedMessage {
  const cached = preparedMessages.get(original);
  if (cached) return cached;
  const message = scrubSubagentUiMessages([original])[0];
  const prepared = {
    message,
    hidden: isSystemCommandTurnId(message.turnId),
  };
  preparedMessages.set(original, prepared);
  return prepared;
}

export function projectWebuiThreadMessages(messages: UIMessage[]): UIMessage[] {
  const visible: UIMessage[] = [];
  const starts = new Map<string, number>();
  let latestStart: number | undefined;
  for (const original of messages) {
    const prepared = prepareMessage(original);
    let message = prepared.message;
    if (prepared.hidden) continue;
    if (message.role === "user" && Number.isFinite(message.createdAt)) {
      latestStart = message.createdAt;
      if (message.turnId) starts.set(message.turnId, message.createdAt);
    }
    // Replay latency starts at the user prompt, not the first assistant output.
    if (message.role === "assistant" && message.kind !== "trace"
      && message.completedAt === undefined && message.latencyMs !== undefined
      && Number.isFinite(message.latencyMs) && message.latencyMs >= 0) {
      const start = message.turnId ? starts.get(message.turnId) : message.source ? undefined : latestStart;
      if (start !== undefined) {
        const completedAt = start + message.latencyMs;
        const cached = completionMessages.get(message);
        if (cached?.completedAt === completedAt) message = cached.message;
        else {
          const completed = { ...message, completedAt };
          completionMessages.set(message, { completedAt, message: completed });
          message = completed;
        }
      }
    }
    visible.push(message);
  }
  return visible;
}

/** Keep empty activity units as source anchors, but remove their redundant task content. */
export function filterThreadDisplayUnits(units: TurnUnit[]): TurnUnit[] {
  return units.map((unit) => unit.type === "activity"
    ? { ...unit, messages: unit.messages.flatMap((message) => {
      const visible = withoutSubagentCreateActivity(message);
      return visible ? [visible] : [];
    }) } : unit);
}

/** Compare history admission, not replay identities, completion times or usage telemetry. */
export function historyContentSnapshot(messages: UIMessage[], forkBoundaryMessageCount: number | null) {
  return { forkBoundary: forkBoundaryMessageCount !== null && forkBoundaryMessageCount > 0,
    messages: filterThreadDisplayUnits(projectActivityTimeline(projectWebuiThreadMessages(messages)))
    .flatMap((unit) => unit.type === "message" ? [unit.message] : unit.messages)
    .map(({ role, kind, renderAs, sideChannel, activityKind, content, reasoning, images, media, traces,
      toolEvents, fileEdits, traceDetail, compaction, cliApps, mcpPresets, sessionMentions, sessionMessage }) =>
      ({ role, kind, renderAs, sideChannel, activityKind, content, reasoning, images, media, traces,
        toolEvents, fileEdits, traceDetail, compaction, cliApps, mcpPresets, sessionMentions, sessionMessage })) };
}

// Display payloads are JSON values. Shared tool results and media need no byte-by-byte serialization.
function sameContentValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left)) {
    return Array.isArray(right) && left.length === right.length
      && left.every((value, index) => sameContentValue(value, right[index]));
  }
  if (Array.isArray(right)) return false;
  const previous = left as Record<string, unknown>;
  const next = right as Record<string, unknown>;
  const keys = Object.keys(previous).filter((key) => previous[key] !== undefined);
  return keys.length === Object.keys(next).filter((key) => next[key] !== undefined).length
    && keys.every((key) => Object.hasOwn(next, key) && sameContentValue(previous[key], next[key]));
}

export function sameHistoryContent(
  previous: ReturnType<typeof historyContentSnapshot>,
  next: ReturnType<typeof historyContentSnapshot>,
): boolean {
  return previous.forkBoundary === next.forkBoundary
    && previous.messages.length === next.messages.length
    && previous.messages.every((message, index) => sameContentValue(message, next.messages[index]));
}
