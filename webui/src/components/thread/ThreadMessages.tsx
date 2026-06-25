import { Fragment, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { MessageBubble } from "@/components/MessageBubble";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { normalizeActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  /** When true, agent turn still in flight — keeps activity timeline expanded. */
  isStreaming?: boolean;
  hiddenUserMessageCount?: number;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
forkBoundaryMessageCount?: number | null;
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
  isStreaming = false,
  hiddenUserMessageCount = 0,
  cliApps = [],
  mcpPresets = [],
forkBoundaryMessageCount = null,
  onOpenFilePreview,
  onForkFromMessage,
}: ThreadMessagesProps) {
  const { t } = useTranslation();
  const units = useMemo(() => buildDisplayUnits(messages, isStreaming), [isStreaming, messages]);
  const forkBoundaryAfterUnitIndex = useMemo(
    () => unitIndexAfterMessageCount(units, forkBoundaryMessageCount),
    [forkBoundaryMessageCount, units],
  );
  const copyFlags = useMemo(() => assistantCopyFlags(units), [units]);
  const liveActivityClusterIndices = useMemo(
    () => isStreaming ? currentActivityClusterIndices(units) : new Set<number>(),
    [isStreaming, units],
  );
  let nextUserIndex = hiddenUserMessageCount;

  return (
    <div className="flex w-full flex-col">
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
        const forkIndex =
          unit.type === "message" && unit.message.role === "assistant" && copyFlags[index]
            ? nextUserIndex
            : undefined;
        if (unit.type === "message" && unit.message.role === "user") nextUserIndex += 1;

        return (
<Fragment key={unitKey(unit, index)}>
            <div className={marginTop} data-user-prompt-id={userPromptId}>
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
                    onForkFromMessage && forkIndex !== undefined
                      ? () => onForkFromMessage(forkIndex)
                      : undefined
                  }
                />
              )}
            </div>
            {index === forkBoundaryAfterUnitIndex ? (
              <ForkBoundaryDivider label={t("thread.forkedFromHistory")} />
            ) : null}
          </Fragment>
        );
      })}
    </div>
  );
}

function unitIndexAfterMessageCount(
  units: DisplayUnit[],
  messageCount: number | null | undefined,
): number | null {
  if (messageCount == null || messageCount <= 0) return null;
  let seen = 0;
  for (let i = 0; i < units.length; i += 1) {
    const unit = units[i];
    seen += unit.type === "activity" ? unit.messages.length : 1;
    if (seen >= messageCount) return i;
  }
  return null;
}

function ForkBoundaryDivider({ label }: { label: string }) {
  return (
    <div className="my-5 flex items-center gap-3 text-[11px] text-muted-foreground/80">
      <span aria-hidden className="h-px flex-1 bg-border/70" />
      <span className="shrink-0">{label}</span>
      <span aria-hidden className="h-px flex-1 bg-border/70" />
    </div>
  );
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
