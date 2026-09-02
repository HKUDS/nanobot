import type { UIMessage } from "@/lib/types";

/** A turn is projected into ordered answer messages and collapsible activity
 * runs. Folding changes presentation only; it never changes semantic order. */
export type TurnUnit =
  | {
      type: "activity";
      messages: UIMessage[];
      /** Number of raw UI messages represented by this display unit. */
      sourceMessageCount: number;
      turnLatencyMs?: number;
      startedAtMs?: number;
    }
  | {
      type: "message";
      message: UIMessage;
      /** Number of raw UI messages represented by this display unit. */
      sourceMessageCount: number;
    };

export function isReasoningOnlyAssistant(message: UIMessage): boolean {
  if (message.role !== "assistant" || message.kind === "trace") return false;
  if (
    message.activityKind === "model"
    || message.content.trim().length > 0
    || !!message.media?.length
    || !!message.images?.length
  ) return false;
  return !!(message.reasoning?.length || message.reasoningStreaming || message.isStreaming);
}

export function isAgentActivityMember(message: UIMessage): boolean {
  return isReasoningOnlyAssistant(message) || message.kind === "trace" || message.activityKind === "model";
}

export function hasPendingAgentActivity(messages: UIMessage[]): boolean {
  const last = messages.at(-1);
  if (!last || !isAgentActivityMember(last)) return false;
  if (last.isStreaming || last.reasoningStreaming) return true;

  const lastTurnId = last.turnId;
  const previous = messages.at(-2);
  // A trace without a visible answer is an unfinished turn on replay. Once a
  // final assistant answer exists after it, the activity is simply history.
  return !previous
    || previous.role !== "assistant"
    || isAgentActivityMember(previous)
    || previous.turnId !== lastTurnId;
}

/** Project gateway rows without changing their causal order.
 *
 * Messages use ``turnSeq`` when every row in the turn provides it and fall
 * back to stable arrival order otherwise. Only contiguous rows of the same
 * display class are combined: activity rows share a collapsible surface, and
 * adjacent answer slices share an answer bubble. A visible answer is always a
 * hard boundary between activity surfaces; completed empty transport frames
 * have no display semantics and therefore create no boundary.
 */
export function normalizeActivityTimeline(
  messages: UIMessage[],
): TurnUnit[] {
  const units: TurnUnit[] = [];
  let turnMessages: UIMessage[] = [];
  let activeTurnId: string | undefined;
  let activeTurnStartedAtMs: number | undefined;

  const flushTurn = () => {
    if (!turnMessages.length) {
      activeTurnId = undefined;
      activeTurnStartedAtMs = undefined;
      return;
    }

    const projected = projectOrderedTurn(
      orderMessagesByTurnSeq(turnMessages),
      activeTurnStartedAtMs,
    );
    if (projected.length) {
      units.push(...projected);
    } else if (units.length) {
      // A turn containing only completed transport placeholders has no
      // display surface. Keep its source count on the preceding prompt so
      // persisted fork-boundary offsets still map to a visible unit.
      const lastIndex = units.length - 1;
      const last = units[lastIndex];
      units[lastIndex] = {
        ...last,
        sourceMessageCount: last.sourceMessageCount + turnMessages.length,
      };
    }

    turnMessages = [];
    activeTurnId = undefined;
    activeTurnStartedAtMs = undefined;
  };

  for (const message of messages) {
    if (message.role === "user") {
      flushTurn();
      units.push({ type: "message", message, sourceMessageCount: 1 });
      activeTurnId = message.turnId;
      activeTurnStartedAtMs = validCreatedAtMs(message.createdAt);
      continue;
    }
    if (message.turnId && activeTurnId && message.turnId !== activeTurnId) flushTurn();
    if (message.turnId) activeTurnId = message.turnId;
    turnMessages.push(message);
  }

  flushTurn();
  return units;
}

export function projectActivityTimeline(
  messages: UIMessage[],
): TurnUnit[] {
  return normalizeActivityTimeline(messages);
}

function projectOrderedTurn(
  messages: UIMessage[],
  startedAtMs?: number,
): TurnUnit[] {
  const units: TurnUnit[] = [];
  let activity: UIMessage[] = [];
  let activitySourceMessageCount = 0;
  let answers: UIMessage[] = [];
  let answerSourceMessageCount = 0;
  let leadingNoopSourceMessageCount = 0;

  const flushActivity = () => {
    if (!activity.length) return;
    units.push({
      type: "activity",
      messages: activity,
      sourceMessageCount: activitySourceMessageCount,
      startedAtMs,
    });
    activity = [];
    activitySourceMessageCount = 0;
  };

  const flushAnswers = () => {
    if (!answers.length) return;
    units.push({
      type: "message",
      message: mergeAssistantAnswers(answers),
      sourceMessageCount: answerSourceMessageCount,
    });
    answers = [];
    answerSourceMessageCount = 0;
  };

  const claimLeadingNoops = () => {
    const count = leadingNoopSourceMessageCount;
    leadingNoopSourceMessageCount = 0;
    return count;
  };

  const appendActivity = (message: UIMessage, sourceMessageCount: number) => {
    flushAnswers();
    activity.push(message);
    activitySourceMessageCount += sourceMessageCount + claimLeadingNoops();
  };

  const absorbDisplayNoop = () => {
    if (activity.length) {
      activitySourceMessageCount += 1;
    } else if (answers.length) {
      answerSourceMessageCount += 1;
    } else {
      leadingNoopSourceMessageCount += 1;
    }
  };

  for (const message of messages) {
    if (isCompletedDisplayNoop(message)) {
      absorbDisplayNoop();
      continue;
    }
    if (isRawActivity(message)) {
      appendActivity(message, 1);
      continue;
    }
    if (isAssistantAnswer(message)) {
      if (message.reasoning?.trim() || message.reasoningStreaming) {
        // This raw message contributes one answer source plus a synthetic
        // reasoning row, so count it only on the answer unit.
        appendActivity(reasoningOnlyMessageFromAnswer(message), 0);
      }
      flushActivity();
      answerSourceMessageCount += claimLeadingNoops();
      answers.push(stripInlineReasoning(message));
      answerSourceMessageCount += 1;
      continue;
    }
    appendActivity(message, 1);
  }

  flushActivity();
  flushAnswers();

  let lastActivityIndex = -1;
  for (let index = units.length - 1; index >= 0; index -= 1) {
    if (units[index].type !== "activity") continue;
    lastActivityIndex = index;
    break;
  }
  if (lastActivityIndex >= 0) {
    const lastActivity = units[lastActivityIndex];
    if (lastActivity.type === "activity") {
      const turnLatencyMs = activityTurnLatencyMs(lastActivity.messages, messages);
      if (turnLatencyMs !== undefined) {
        units[lastActivityIndex] = { ...lastActivity, turnLatencyMs };
      }
    }
  }
  return units;
}

function isRawActivity(message: UIMessage): boolean {
  return isAgentActivityMember(message);
}

/** A completed transport placeholder carries ordering/accounting metadata but
 * no user-visible semantics, so it cannot define a display boundary. */
function isCompletedDisplayNoop(message: UIMessage): boolean {
  return (
    message.role === "assistant"
    && message.kind !== "trace"
    && message.activityKind !== "model"
    && !message.isStreaming
    && !message.reasoningStreaming
    && message.content.trim().length === 0
    && !message.reasoning?.trim()
    && !message.media?.length
    && !message.images?.length
    && !message.traces?.some((line) => line.trim().length > 0)
    && !message.toolEvents?.length
    && !message.fileEdits?.length
    && !message.sessionMessage
  );
}

function isAssistantAnswer(message: UIMessage): boolean {
  if (message.role !== "assistant" || message.kind === "trace" || message.activityKind === "model") {
    return false;
  }
  if (message.turnPhase === "reasoning" || message.turnPhase === "activity") return false;
  return (
    message.turnPhase === "answer"
    || message.content.trim().length > 0
    || !!message.media?.length
    || !!message.images?.length
  );
}

function orderMessagesByTurnSeq(messages: UIMessage[]): UIMessage[] {
  if (messages.length < 2 || !messages.every((message) => Number.isFinite(message.turnSeq))) {
    return messages;
  }
  return messages
    .map((message, index) => ({ message, index }))
    .sort((left, right) => (left.message.turnSeq! - right.message.turnSeq!) || (left.index - right.index))
    .map(({ message }) => message);
}

function mergeAssistantAnswers(answers: UIMessage[]): UIMessage {
  const first = answers[0];
  const last = answers.at(-1)!;
  const media = answers.flatMap((message) => message.media ?? []);
  const images = answers.flatMap((message) => message.images ?? []);
  const merged: UIMessage = {
    ...first,
    ...last,
    id: first.id,
    content: answers.map((message) => message.content.trim()).filter(Boolean).join("\n\n"),
    createdAt: first.createdAt,
    isStreaming: answers.some((message) => message.isStreaming),
  };
  if (media.length) merged.media = media;
  else delete merged.media;
  if (images.length) merged.images = images;
  else delete merged.images;
  return merged;
}

function reasoningOnlyMessageFromAnswer(message: UIMessage): UIMessage {
  return {
    id: `${message.id}-reasoning`,
    role: "assistant",
    content: "",
    createdAt: message.createdAt,
    reasoning: message.reasoning,
    reasoningStreaming: message.reasoningStreaming,
    isStreaming: message.reasoningStreaming,
    activitySegmentId: message.activitySegmentId,
    latencyMs: message.latencyMs,
    turnId: message.turnId,
    turnPhase: "reasoning",
    turnSeq: message.turnSeq,
  };
}

function stripInlineReasoning(message: UIMessage): UIMessage {
  const next = { ...message };
  delete next.reasoning;
  delete next.reasoningStreaming;
  return next;
}

function validCreatedAtMs(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function activityTurnLatencyMs(activityMessages: UIMessage[], allMessages: UIMessage[]): number | undefined {
  for (let index = allMessages.length - 1; index >= 0; index -= 1) {
    const latency = allMessages[index].latencyMs;
    if (isValidLatency(latency)) return latency;
  }
  for (let index = activityMessages.length - 1; index >= 0; index -= 1) {
    const latency = activityMessages[index].latencyMs;
    if (isValidLatency(latency)) return latency;
  }
  return undefined;
}

function isValidLatency(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}
