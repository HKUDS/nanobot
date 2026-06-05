import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { MessageBubble } from "@/components/MessageBubble";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { normalizeActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  allMessages?: UIMessage[];
  /** When true, agent turn still in flight — keeps activity timeline expanded. */
  isStreaming?: boolean;
  hiddenMessageCount?: number;
  onLoadEarlier?: () => void;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  onOpenFilePreview?: (path: string) => void;
  onForkFromMessage?: (beforeUserIndex: number) => void;
}

export type DisplayUnit = TurnUnit;

/** True when this unit index is the last assistant text slice before the next user message (or end of thread). */
export function isFinalAssistantSliceBeforeNextUser(
  units: DisplayUnit[],
  index: number,
): boolean {
  const u = units[index];
  if (u.type !== "message" || u.message.role !== "assistant") return true;
  for (let j = index + 1; j < units.length; j++) {
    const v = units[j];
    if (v.type === "message" && v.message.role === "user") break;
    return false;
  }
  return true;
}

export function buildDisplayUnits(
  messages: UIMessage[],
  isStreaming = false,
): DisplayUnit[] {
  return normalizeActivityTimeline(messages, {
    preserveTrailingActivity: isStreaming,
  });
}

export function assistantCopyFlags(units: DisplayUnit[]): boolean[] {
  const flags = new Array<boolean>(units.length).fill(true);
  let hasLaterUnitBeforeUser = false;
  for (let i = units.length - 1; i >= 0; i -= 1) {
    const unit = units[i];
    if (unit.type === "message" && unit.message.role === "user") {
      hasLaterUnitBeforeUser = false;
      continue;
    }
    if (unit.type === "message" && unit.message.role === "assistant") {
      flags[i] = !hasLaterUnitBeforeUser;
    }
    hasLaterUnitBeforeUser = true;
  }
  return flags;
}

export function ThreadMessages({
  messages,
  allMessages,
  isStreaming = false,
  hiddenMessageCount = 0,
  onLoadEarlier,
  cliApps = [],
  mcpPresets = [],
  onOpenFilePreview,
  onForkFromMessage,
}: ThreadMessagesProps) {
  const { t } = useTranslation();
  const units = useMemo(() => buildDisplayUnits(messages, isStreaming), [isStreaming, messages]);
  const assistantForkIndexById = useMemo(
    () => assistantForkIndexByMessageId(allMessages ?? messages),
    [allMessages, messages],
  );
  const copyFlags = useMemo(() => assistantCopyFlags(units), [units]);
  const liveActivityClusterIndices = useMemo(
    () => isStreaming ? currentActivityClusterIndices(units) : new Set<number>(),
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
          unit.type === "activity"
          && next?.type === "message"
          && next.message.role === "assistant";

        const userPromptId =
          unit.type === "message" && unit.message.role === "user"
            ? unit.message.id
            : undefined;

        return (
          <div
            key={unitKey(unit, index)}
            className={marginTop}
            data-user-prompt-id={userPromptId}
          >
            {unit.type === "activity" ? (
              <AgentActivityCluster
                messages={unit.messages}
                isTurnStreaming={liveActivityClusterIndices.has(index)}
                hasBodyBelow={hasBodyBelow}
                turnLatencyMs={unit.turnLatencyMs}
                cliApps={cliApps}
                mcpPresets={mcpPresets}
                onOpenFilePreview={onOpenFilePreview}
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
                onOpenFilePreview={onOpenFilePreview}
                onForkFromHere={
                  onForkFromMessage
                    ? forkHandlerForAssistantMessage(
                        unit.message,
                        copyFlags[index],
                        assistantForkIndexById,
                        onForkFromMessage,
                      )
                    : undefined
                }
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function assistantForkIndexByMessageId(messages: UIMessage[]): Map<string, number> {
  const out = new Map<string, number>();
  let nextUserIndex = 0;
  for (const message of messages) {
    if (message.role === "user") {
      nextUserIndex += 1;
    } else if (message.role === "assistant") {
      out.set(message.id, nextUserIndex);
    }
  }
  return out;
}

function forkHandlerForAssistantMessage(
  message: UIMessage,
  canForkAssistant: boolean,
  assistantForkIndexById: Map<string, number>,
  onForkFromMessage: NonNullable<ThreadMessagesProps["onForkFromMessage"]>,
): (() => void) | undefined {
  if (message.role === "assistant" && canForkAssistant) {
    const beforeUserIndex = assistantForkIndexById.get(message.id);
    return beforeUserIndex === undefined
      ? undefined
      : () => onForkFromMessage(beforeUserIndex);
  }
  return undefined;
}

function currentActivityClusterIndices(units: DisplayUnit[]): Set<number> {
  const indices = new Set<number>();
  let markedCurrentActivity = false;
  for (let i = units.length - 1; i >= 0; i -= 1) {
    const unit = units[i];
    if (unit.type === "activity") {
      if (!markedCurrentActivity) {
        indices.add(i);
        markedCurrentActivity = true;
      }
      continue;
    }
    if (unit.message.role === "assistant" && unit.message.isStreaming) continue;
    if (unit.message.role === "user") break;
  }
  return indices;
}

function unitKey(unit: DisplayUnit, index: number): string {
  if (unit.type === "activity") {
    const anchor = unit.messages[0]?.id;
    return anchor != null ? `activity-${anchor}` : `activity-idx-${index}`;
  }
  return unit.message.id;
}

function marginAfterPrevUnit(prev: DisplayUnit): string {
  if (prev.type === "activity") {
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
