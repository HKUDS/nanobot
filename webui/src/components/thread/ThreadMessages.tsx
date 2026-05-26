import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { MessageBubble } from "@/components/MessageBubble";
import {
  AgentActivityCluster,
  isAgentActivityMember,
} from "@/components/thread/AgentActivityCluster";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  /** When true, agent turn still in flight — keeps activity cluster expanded. */
  isStreaming?: boolean;
  hiddenMessageCount?: number;
  onLoadEarlier?: () => void;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
}

export type DisplayUnit =
  | { type: "cluster"; messages: UIMessage[] }
  | { type: "single"; message: UIMessage };

/** True when this unit index is the last assistant text slice before the next user message (or end of thread). */
export function isFinalAssistantSliceBeforeNextUser(
  units: DisplayUnit[],
  index: number,
): boolean {
  const u = units[index];
  if (u.type !== "single" || u.message.role !== "assistant") return true;
  for (let j = index + 1; j < units.length; j++) {
    const v = units[j];
    if (v.type === "single" && v.message.role === "user") break;
    return false;
  }
  return true;
}

export function buildDisplayUnits(messages: UIMessage[]): DisplayUnit[] {
  const out: DisplayUnit[] = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (isAgentActivityMember(m)) {
      const cluster: UIMessage[] = [];
      let segmentId: string | undefined = m.activitySegmentId;
      let clusterHasFileEdits = hasFileEdits(m);
      while (
        i < messages.length
        && isAgentActivityMember(messages[i])
        && canJoinActivityCluster(segmentId, clusterHasFileEdits, messages[i])
      ) {
        const current = messages[i];
        if (!segmentId && current.activitySegmentId) {
          segmentId = current.activitySegmentId;
        }
        clusterHasFileEdits = clusterHasFileEdits || hasFileEdits(current);
        cluster.push(current);
        i += 1;
      }
      out.push({ type: "cluster", messages: cluster });
      continue;
    }
    const previous = out[out.length - 1];
    if (
      previous?.type === "cluster"
      && assistantHasInlineReasoning(m)
      && canFoldInlineReasoning(previous.messages, m)
    ) {
      previous.messages.push(reasoningOnlyMessageFromAnswer(m));
      out.push({ type: "single", message: stripInlineReasoning(m) });
      i += 1;
      continue;
    }
    if (assistantHasInlineReasoning(m)) {
      out.push({ type: "cluster", messages: [reasoningOnlyMessageFromAnswer(m)] });
      out.push({ type: "single", message: stripInlineReasoning(m) });
      i += 1;
      continue;
    }
    out.push({ type: "single", message: m });
    i += 1;
  }
  return out;
}

function clusterSegmentId(messages: UIMessage[]): string | undefined {
  return messages.find((message) => message.activitySegmentId)?.activitySegmentId;
}

function hasFileEdits(message: UIMessage): boolean {
  return !!message.fileEdits?.length;
}

function clusterHasFileEdits(messages: UIMessage[]): boolean {
  return messages.some(hasFileEdits);
}

function canJoinActivityCluster(
  clusterSegmentId: string | undefined,
  clusterIncludesFileEdits: boolean,
  message: UIMessage,
): boolean {
  const messageHasFileEdits = hasFileEdits(message);
  if (!clusterIncludesFileEdits && !messageHasFileEdits) return true;
  if (!clusterSegmentId || !message.activitySegmentId) return true;
  return clusterSegmentId === message.activitySegmentId;
}

function canFoldInlineReasoning(cluster: UIMessage[], message: UIMessage): boolean {
  if (!clusterHasFileEdits(cluster) && !hasFileEdits(message)) return true;
  const segmentId = clusterSegmentId(cluster);
  if (!segmentId || !message.activitySegmentId) return true;
  return segmentId === message.activitySegmentId;
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

export function assistantCopyFlags(units: DisplayUnit[]): boolean[] {
  const flags = new Array<boolean>(units.length).fill(true);
  let hasLaterUnitBeforeUser = false;
  for (let i = units.length - 1; i >= 0; i -= 1) {
    const unit = units[i];
    if (unit.type === "single" && unit.message.role === "user") {
      hasLaterUnitBeforeUser = false;
      continue;
    }
    if (unit.type === "single" && unit.message.role === "assistant") {
      flags[i] = !hasLaterUnitBeforeUser;
    }
    hasLaterUnitBeforeUser = true;
  }
  return flags;
}

export function ThreadMessages({
  messages,
  isStreaming = false,
  hiddenMessageCount = 0,
  onLoadEarlier,
  cliApps = [],
  mcpPresets = [],
}: ThreadMessagesProps) {
  const { t } = useTranslation();
  const units = useMemo(() => buildDisplayUnits(messages), [messages]);
  const copyFlags = useMemo(() => assistantCopyFlags(units), [units]);
  const liveActivityClusterIndex = useMemo(
    () => isStreaming ? currentActivityClusterIndex(units) : -1,
    [isStreaming, units],
  );

  return (
    <div className="flex w-full flex-col">
      {hiddenMessageCount > 0 && onLoadEarlier ? (
        <div className="mb-4 flex justify-center">
          <button
            type="button"
            onClick={onLoadEarlier}
            className="rounded-full border border-border/60 bg-background/85 px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-sm transition-colors hover:bg-muted/55 hover:text-foreground"
          >
            {t("thread.loadEarlier", {
              count: hiddenMessageCount,
              defaultValue: "Load earlier messages",
            })}
          </button>
        </div>
      ) : null}
      {units.map((unit, index) => {
        const prev = units[index - 1];
        const marginTop =
          index > 0
            ? marginAfterPrevUnit(prev)
            : "";
        const next = units[index + 1];
        const hasBodyBelow =
          unit.type === "cluster"
          && next?.type === "single"
          && next.message.role === "assistant";
        const turnLatencyMs =
          unit.type === "cluster" ? activityClusterTurnLatencyMs(unit.messages, next) : undefined;

        return (
          <div key={unitKey(unit, index)} className={marginTop}>
            {unit.type === "cluster" ? (
              <AgentActivityCluster
                messages={unit.messages}
                isTurnStreaming={index === liveActivityClusterIndex}
                hasBodyBelow={hasBodyBelow}
                turnLatencyMs={turnLatencyMs}
                cliApps={cliApps}
                mcpPresets={mcpPresets}
              />
            ) : (
              <MessageBubble
                message={unit.message}
                showAssistantCopyAction={
                  unit.message.role === "assistant"
                    ? copyFlags[index]
                    : true
                }
                cliApps={cliApps}
                mcpPresets={mcpPresets}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function activityClusterTurnLatencyMs(
  messages: UIMessage[],
  next: DisplayUnit | undefined,
): number | undefined {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const latency = messages[i].latencyMs;
    if (typeof latency === "number" && Number.isFinite(latency) && latency >= 0) {
      return latency;
    }
  }
  if (
    next?.type === "single"
    && next.message.role === "assistant"
    && typeof next.message.latencyMs === "number"
    && Number.isFinite(next.message.latencyMs)
    && next.message.latencyMs >= 0
  ) {
    return next.message.latencyMs;
  }
  return undefined;
}

function currentActivityClusterIndex(units: DisplayUnit[]): number {
  const last = units.length - 1;
  return units[last]?.type === "cluster" ? last : -1;
}

function unitKey(unit: DisplayUnit, index: number): string {
  if (unit.type === "cluster") {
    const anchor = unit.messages[0]?.id;
    return anchor != null ? `cluster-${anchor}` : `cluster-idx-${index}`;
  }
  return unit.message.id;
}

function marginAfterPrevUnit(prev: DisplayUnit): string {
  if (prev.type === "cluster") {
    return "mt-4";
  }
  const p = prev.message;
  const denseP =
    p.kind === "trace"
    || (
      p.role === "assistant"
      && p.content.trim().length === 0
      && (!!p.reasoning || !!p.reasoningStreaming)
    );
  if (denseP) {
    return "mt-2";
  }
  return "mt-5";
}
