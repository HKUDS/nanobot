import { toMediaAttachment } from "@/lib/media";
import type { ToolProgressEvent, UIMediaAttachment, UIMessage } from "@/lib/types";

export type ActivityItemType = "reasoning" | "tool" | "cli" | "mcp" | "file_edit" | "media";
export type ActivityStepStatus = "pending" | "running" | "done" | "error";
export type ActivityStepSource = "reasoning" | "tool" | "web" | "browser" | "shell" | "mcp" | "file" | "media";

export interface ActivityItem {
  type: ActivityItemType;
  message: UIMessage;
}

export interface ActivityEvidence {
  id: string;
  attachment: UIMediaAttachment;
  caption?: string;
  source: ActivityStepSource;
}

export interface ActivityStepItem {
  id: string;
  label: string;
  detail?: string;
  status: ActivityStepStatus;
  source: ActivityStepSource;
  preview?: ActivityEvidence[];
  error?: string;
}

export interface ActivityGroup {
  id: string;
  title: string;
  source: ActivityStepSource;
  steps: ActivityStepItem[];
}

export type TurnUnit =
  | { type: "activity"; messages: UIMessage[]; items: ActivityItem[]; turnLatencyMs?: number }
  | { type: "message"; message: UIMessage };

interface NormalizeActivityTimelineOptions {
  preserveTrailingActivity?: boolean;
}

export function isReasoningOnlyAssistant(message: UIMessage): boolean {
  if (message.role !== "assistant" || message.kind === "trace") return false;
  if (message.content.trim().length > 0) return false;
  return !!(message.reasoning?.length || message.reasoningStreaming || message.isStreaming);
}

export function isAgentActivityMember(message: UIMessage): boolean {
  return isReasoningOnlyAssistant(message) || message.kind === "trace";
}

export function hasPendingAgentActivity(messages: UIMessage[]): boolean {
  if (messages.length === 0) return false;
  const last = messages[messages.length - 1];
  if (!isAgentActivityMember(last)) return false;

  let trailingStart = messages.length - 1;
  while (
    trailingStart > 0
    && isAgentActivityMember(messages[trailingStart - 1])
  ) {
    trailingStart -= 1;
  }

  const trailing = messages.slice(trailingStart);
  if (trailing.some((message) => message.isStreaming || message.reasoningStreaming)) {
    return true;
  }

  const previous = messages[trailingStart - 1];
  if (!previous || previous.role !== "assistant" || isAgentActivityMember(previous)) {
    return true;
  }

  const trailingTurnIds = new Set(
    trailing
      .map((message) => message.turnId)
      .filter((turnId): turnId is string => typeof turnId === "string" && turnId.length > 0),
  );
  if (!previous.turnId) return trailingTurnIds.size > 0;
  return trailingTurnIds.size > 0 && !trailingTurnIds.has(previous.turnId);
}

export function normalizeActivityTimeline(
  messages: UIMessage[],
  options: NormalizeActivityTimelineOptions = {},
): TurnUnit[] {
  const units: TurnUnit[] = [];
  let turnMessages: UIMessage[] = [];
  let activeTurnId: string | undefined;

  const flushTurn = (flushOptions: NormalizeActivityTimelineOptions = {}) => {
    if (turnMessages.length === 0) return;

    const turnUnits: TurnUnit[] = [];
    const orderedTurnMessages = orderMessagesByTurnSeq(turnMessages);
    const visibleMessages = visibleMessagesForTurn(orderedTurnMessages);
    let visibleIndex = 0;
    let activityMessages: UIMessage[] = [];

    const flushActivityMessages = () => {
      if (!activityMessages.length) return;
      pushActivityUnits(turnUnits, activityMessages, visibleMessages.slice(visibleIndex));
      activityMessages = [];
    };

    for (const message of orderedTurnMessages) {
      if (isAgentActivityMember(message)) {
        activityMessages.push(message);
        continue;
      }

      if (assistantHasInlineReasoning(message)) {
        activityMessages.push(reasoningOnlyMessageFromAnswer(message));
        flushActivityMessages();
        turnUnits.push({ type: "message", message: stripInlineReasoning(message) });
        visibleIndex += 1;
        continue;
      }

      flushActivityMessages();
      turnUnits.push({ type: "message", message });
      visibleIndex += 1;
    }

    flushActivityMessages();
    units.push(...normalizeCompletedTurnUnits(turnUnits, flushOptions));
    turnMessages = [];
    activeTurnId = undefined;
  };

  for (const message of messages) {
    if (message.role === "user") {
      flushTurn();
      units.push({ type: "message", message });
      activeTurnId = message.turnId;
      continue;
    }

    if (message.turnId && activeTurnId && message.turnId !== activeTurnId) {
      flushTurn();
    }
    if (message.turnId) {
      activeTurnId = message.turnId;
    }
    turnMessages.push(message);
  }

  flushTurn(options);
  return units;
}

function orderMessagesByTurnSeq(messages: UIMessage[]): UIMessage[] {
  if (
    messages.length < 2
    || !messages.every((message) => Number.isFinite(message.turnSeq))
  ) {
    return messages;
  }
  return messages
    .map((message, index) => ({ message, index }))
    .sort((left, right) => {
      const bySeq = (left.message.turnSeq ?? 0) - (right.message.turnSeq ?? 0);
      return bySeq || left.index - right.index;
    })
    .map(({ message }) => message);
}

function normalizeCompletedTurnUnits(
  turnUnits: TurnUnit[],
  options: NormalizeActivityTimelineOptions,
): TurnUnit[] {
  if (options.preserveTrailingActivity || turnUnits.length < 2) return turnUnits;
  if (turnUnits[turnUnits.length - 1]?.type !== "activity") return turnUnits;

  let trailingStart = turnUnits.length - 1;
  while (trailingStart > 0 && turnUnits[trailingStart - 1]?.type === "activity") {
    trailingStart -= 1;
  }

  const previous = turnUnits[trailingStart - 1];
  if (
    !previous
    || previous.type !== "message"
    || previous.message.role !== "assistant"
  ) {
    return turnUnits;
  }

  return [
    ...turnUnits.slice(0, trailingStart - 1),
    ...turnUnits.slice(trailingStart),
    previous,
  ];
}

function visibleMessagesForTurn(messages: UIMessage[]): UIMessage[] {
  const visibleMessages: UIMessage[] = [];
  for (const message of messages) {
    if (isAgentActivityMember(message)) continue;
    visibleMessages.push(assistantHasInlineReasoning(message) ? stripInlineReasoning(message) : message);
  }
  return visibleMessages;
}

function pushActivityUnits(units: TurnUnit[], activityMessages: UIMessage[], visibleMessages: UIMessage[]) {
  let runMessages: UIMessage[] = [];
  let runBucket: "file" | "other" | undefined;
  let runSegmentId: string | undefined;

  const flushRun = () => {
    if (!runMessages.length) return;
    units.push({
      type: "activity",
      messages: runMessages,
      items: runMessages.flatMap(activityItemsForMessage),
      turnLatencyMs: activityTurnLatencyMs(runMessages, visibleMessages),
    });
    runMessages = [];
    runBucket = undefined;
    runSegmentId = undefined;
  };

  for (const message of activityMessages) {
    const bucket = isFileEditActivityMessage(message) ? "file" : "other";
    const segmentId = message.activitySegmentId;
    const segmentChanged =
      bucket === "file"
      && runBucket === "file"
      && !!runSegmentId
      && !!segmentId
      && runSegmentId !== segmentId;
    if ((runBucket && bucket !== runBucket) || segmentChanged) {
      flushRun();
    }
    runBucket = bucket;
    if (segmentId) runSegmentId = segmentId;
    runMessages.push(message);
  }

  flushRun();
}

function isFileEditActivityMessage(message: UIMessage): boolean {
  return message.kind === "trace" && !!message.fileEdits?.length;
}

function assistantHasInlineReasoning(message: UIMessage): boolean {
  return (
    message.role === "assistant"
    && message.kind !== "trace"
    && message.content.trim().length > 0
    && (!!message.reasoning?.trim() || !!message.reasoningStreaming)
  );
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
  };
}

function stripInlineReasoning(message: UIMessage): UIMessage {
  const next = { ...message };
  delete next.reasoning;
  delete next.reasoningStreaming;
  return next;
}

function activityItemsForMessage(message: UIMessage): ActivityItem[] {
  if (isReasoningOnlyAssistant(message)) {
    return [{ type: "reasoning", message }];
  }
  if (message.kind !== "trace") return [];

  const items: ActivityItem[] = [];
  if (message.fileEdits?.length) {
    items.push({ type: "file_edit", message });
  }
  for (const event of message.toolEvents ?? []) {
    const name = String(event.name ?? "").toLowerCase();
    if (name === "run_cli_app") {
      items.push({ type: "cli", message });
    } else if (name === "mcp") {
      items.push({ type: "mcp", message });
    } else {
      items.push({ type: "tool", message });
    }
  }
  if (items.length === 0 && (message.traces?.length || message.content.trim())) {
    items.push({ type: "tool", message });
  }
  if (message.media?.length) {
    items.push({ type: "media", message });
  }
  return items;
}

function activityTurnLatencyMs(activityMessages: UIMessage[], visibleMessages: UIMessage[]): number | undefined {
  for (let i = activityMessages.length - 1; i >= 0; i -= 1) {
    const latency = activityMessages[i].latencyMs;
    if (isValidLatency(latency)) return latency;
  }
  for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
    const latency = visibleMessages[i].latencyMs;
    if (isValidLatency(latency)) return latency;
  }
  return undefined;
}

function isValidLatency(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function activityEvidenceFromToolEvent(event: ToolProgressEvent): ActivityEvidence[] {
  const source = activitySourceFromToolName(toolEventName(event));
  const evidence: ActivityEvidence[] = [];
  const extras = [
    ...unknownList((event as { embeds?: unknown }).embeds),
    ...unknownList((event as { files?: unknown }).files),
  ];
  extras.forEach((value, index) => {
    const attachment = mediaAttachmentFromUnknown(value);
    if (!attachment) return;
    evidence.push({
      id: `${event.call_id || toolEventName(event) || "tool"}:${index}:${attachment.url || attachment.name || attachment.kind}`,
      attachment,
      caption: attachment.name,
      source,
    });
  });
  return evidence;
}

export function activityEvidenceFromMessageMedia(message: UIMessage): ActivityEvidence[] {
  return (message.media ?? []).map((attachment, index) => ({
    id: `${message.id}:media:${index}:${attachment.url || attachment.name || attachment.kind}`,
    attachment,
    caption: attachment.name,
    source: "media",
  }));
}

function unknownList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function toolEventName(event: ToolProgressEvent): string {
  return typeof (event as { function?: { name?: unknown } }).function?.name === "string"
    ? String((event as { function?: { name?: unknown } }).function?.name)
    : typeof event.name === "string"
      ? event.name
      : "";
}

function activitySourceFromToolName(name: string): ActivityStepSource {
  const compact = name.toLowerCase();
  if (compact.includes("browser") || compact.includes("screenshot")) return "browser";
  if (compact.includes("web") || compact.includes("search") || compact.includes("fetch") || compact.includes("read")) return "web";
  if (compact.includes("exec") || compact.includes("shell") || compact.includes("cli")) return "shell";
  if (compact.startsWith("mcp_") || compact === "mcp") return "mcp";
  if (compact.includes("file") || compact.includes("patch")) return "file";
  if (compact.includes("image") || compact.includes("video") || compact.includes("media")) return "media";
  return "tool";
}

function mediaAttachmentFromUnknown(value: unknown): UIMediaAttachment | null {
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return null;
    return toMediaAttachment({ url: looksLikeUrl(text) ? text : undefined, name: baseName(text) });
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const url = stringField(record, ["url", "href", "src", "uri", "signed_url", "thumbnail_url"]);
  const path = stringField(record, ["path", "absolute_path", "file", "filename"]);
  const name = stringField(record, ["name", "filename", "title", "label"]) ?? baseName(url ?? path ?? "");
  const kind = mediaKindFromRecord(record, url, name);
  return toMediaAttachment({ url, name, kind });
}

function stringField(record: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function mediaKindFromRecord(record: Record<string, unknown>, url?: string, name?: string): UIMediaAttachment["kind"] | undefined {
  const raw = stringField(record, ["kind", "type", "mime", "mime_type", "content_type"])?.toLowerCase() ?? "";
  if (raw.includes("image") || raw.includes("screenshot")) return "image";
  if (raw.includes("video") || raw.includes("mp4") || raw.includes("quicktime")) return "video";
  if (raw.includes("file") || raw.includes("document")) return "file";
  return toMediaAttachment({ url, name }).kind;
}

function looksLikeUrl(value: string): boolean {
  return /^(https?:|data:|\/api\/|blob:)/i.test(value);
}

function baseName(value: string): string | undefined {
  const clean = value.split(/[?#]/, 1)[0] ?? "";
  const last = clean.split(/[\\/]/).filter(Boolean).pop();
  return last || undefined;
}
