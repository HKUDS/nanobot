import { memo, useCallback, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { MessageBubble } from "@/components/MessageBubble";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { AssistantSelectionAction } from "@/components/thread/AssistantSelectionAction";
import { projectActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import type { CliAppInfo, McpPresetInfo, SlashCommand, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  temporary?: boolean;
  /** When true, agent turn still in flight — keeps activity timeline expanded. */
  isStreaming?: boolean;
  activeTurnId?: string | null;
  /** Optimistic or canonical active-turn start, in unix seconds. */
  runStartedAt?: number | null;
  hiddenUserMessageCount?: number;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  slashCommands?: SlashCommand[];
  forkBoundaryMessageCount?: number | null;
  onOpenFilePreview?: (path: string) => void;
  onForkFromMessage?: (beforeUserIndex: number) => void;
  onQuoteSelection?: (text: string) => void;
}

export type DisplayUnit = TurnUnit;

export function buildDisplayUnits(messages: UIMessage[]): DisplayUnit[] {
  return projectActivityTimeline(messages);
}

export function assistantForkFlags(units: DisplayUnit[]): boolean[] {
  const flags = new Array<boolean>(units.length).fill(true);
  let hasLaterUnitBeforeUser = false;
  for (let i = units.length - 1; i >= 0; i -= 1) {
    const unit = units[i];
    if (unit.type === "message" && unit.message.role === "user") {
      hasLaterUnitBeforeUser = false;
      continue;
    }
    if (
      unit.type === "message"
      && unit.message.role === "assistant"
      && unit.message.kind === "compaction"
    ) {
      // Compaction notices are session lifecycle markers, not assistant answers.
      // They must neither expose nor displace the answer-level fork action.
      flags[i] = false;
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
  temporary = false,
  isStreaming = false,
  activeTurnId = null,
  runStartedAt = null,
  hiddenUserMessageCount = 0,
  cliApps = [],
  mcpPresets = [],
  slashCommands = [],
  forkBoundaryMessageCount = null,
  onOpenFilePreview,
  onForkFromMessage,
  onQuoteSelection,
}: ThreadMessagesProps) {
  const { t } = useTranslation();
  const messageListRef = useRef<HTMLDivElement>(null);
  const units = useMemo(
    () => buildDisplayUnits(messages),
    [messages],
  );
  const forkBoundaryAfterUnitIndex = useMemo(
    () => unitIndexAfterMessageCount(units, forkBoundaryMessageCount),
    [forkBoundaryMessageCount, units],
  );
  const forkFlags = useMemo(() => assistantForkFlags(units), [units]);
  const liveActivityClusterIndices = useMemo(
    () => isStreaming
      ? currentActivityClusterIndices(units, activeTurnId)
      : new Set<number>(),
    [activeTurnId, isStreaming, units],
  );
  const pendingTurn = useMemo(
    () => pendingTurnProjection(messages, activeTurnId),
    [activeTurnId, messages],
  );
  const pendingActivity = (
    isStreaming
    && liveActivityClusterIndices.size === 0
    && pendingTurn !== null
    && !pendingTurn.hasVisibleOutput
  ) ? pendingTurn : null;
  const currentTurnStartIndex = isStreaming
    ? activeTurnStartIndex(units, activeTurnId)
    : units.length;
  const unitKeys = useMemo(() => unitKeysForDisplay(units), [units]);
  let nextUserIndex = hiddenUserMessageCount;

  return (
    <div ref={messageListRef} className="flex w-full flex-col">
      <AssistantSelectionAction
        containerRef={messageListRef}
        onQuoteSelection={onQuoteSelection}
      />
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
        const deferOffscreenRender =
          index < units.length - 1
          && (
            unit.type === "activity"
              ? !liveActivityClusterIndices.has(index)
              : unit.message.role === "assistant" && !unit.message.isStreaming
          );
        const userPromptId =
          unit.type === "message" && unit.message.role === "user"
            ? unit.message.id
            : undefined;
        const forkIndex =
          unit.type === "message" && unit.message.role === "assistant" && forkFlags[index]
            ? nextUserIndex
            : undefined;
        if (
          unit.type === "message"
          && unit.message.role === "user"
          && unit.message.deliveryStatus !== "failed"
        ) nextUserIndex += 1;

        return (
          <ThreadDisplayUnit
            key={unitKeys[index]}
            unitKey={unitKeys[index]}
            unit={unit}
            marginTop={marginTop}
            userPromptId={userPromptId}
            hasBodyBelow={hasBodyBelow}
            deferOffscreenRender={deferOffscreenRender}
            isTurnStreaming={
              unit.type === "activity"
                ? liveActivityClusterIndices.has(index)
                : isStreaming && (
                    unit.message.turnId && activeTurnId !== null
                      ? unit.message.turnId === activeTurnId
                      : index > currentTurnStartIndex
                  )
            }
            forkIndex={forkIndex}
            showForkBoundary={index === forkBoundaryAfterUnitIndex}
            forkBoundaryLabel={t("thread.forkedFromHistory")}
            temporary={temporary}
            cliApps={cliApps}
            mcpPresets={mcpPresets}
            slashCommands={slashCommands}
            onOpenFilePreview={onOpenFilePreview}
            onForkFromMessage={onForkFromMessage}
          />
        );
      })}
      {pendingActivity ? (
        <div className={units.length > 0 ? "mt-5" : undefined}>
          <AgentActivityCluster
            messages={[]}
            isTurnStreaming
            hasBodyBelow={false}
            startedAtMs={
              runStartedAt != null
                ? runStartedAt * 1000
                : pendingActivity.startedAtMs
            }
          />
        </div>
      ) : null}
    </div>
  );
}

interface PendingTurnProjection {
  startedAtMs?: number;
  hasVisibleOutput: boolean;
}

function pendingTurnProjection(
  messages: UIMessage[],
  activeTurnId: string | null,
): PendingTurnProjection | null {
  let promptIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === "user"
      && message.deliveryStatus !== "failed"
      && (activeTurnId === null || message.turnId === activeTurnId)
    ) {
      promptIndex = index;
      break;
    }
  }
  if (promptIndex < 0) return null;

  const prompt = messages[promptIndex];
  const hasVisibleOutput = messages.slice(promptIndex + 1).some((message) => {
    if (message.role === "user") return false;
    if (activeTurnId && message.turnId && message.turnId !== activeTurnId) return false;
    return (
      message.content.trim().length > 0
      || !!message.reasoning?.trim()
      || !!message.reasoningStreaming
      || message.kind === "trace"
      || !!message.media?.length
    );
  });

  return {
    ...(typeof prompt.createdAt === "number" && Number.isFinite(prompt.createdAt)
      ? { startedAtMs: prompt.createdAt }
      : {}),
    hasVisibleOutput,
  };
}

interface ThreadDisplayUnitProps {
  unitKey: string;
  unit: DisplayUnit;
  marginTop: string;
  userPromptId?: string;
  hasBodyBelow: boolean;
  deferOffscreenRender: boolean;
  isTurnStreaming: boolean;
  forkIndex?: number;
  showForkBoundary: boolean;
  forkBoundaryLabel: string;
  temporary: boolean;
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
  slashCommands: SlashCommand[];
  onOpenFilePreview?: (path: string) => void;
  onForkFromMessage?: (beforeUserIndex: number) => void;
}

const ThreadDisplayUnit = memo(function ThreadDisplayUnit({
  unitKey,
  unit,
  marginTop,
  userPromptId,
  hasBodyBelow,
  deferOffscreenRender,
  isTurnStreaming,
  forkIndex,
  showForkBoundary,
  forkBoundaryLabel,
  temporary,
  cliApps,
  mcpPresets,
  slashCommands,
  onOpenFilePreview,
  onForkFromMessage,
}: ThreadDisplayUnitProps) {
  // Introducing content-visibility after a unit has painted can move the
  // browser's scroll anchor. Only units deferred on their first render may
  // remain deferred.
  const hasRenderedEagerlyRef = useRef(!deferOffscreenRender);
  if (!deferOffscreenRender) hasRenderedEagerlyRef.current = true;
  const stableDeferOffscreenRender =
    deferOffscreenRender && !hasRenderedEagerlyRef.current;
  const onForkFromHere = useCallback(() => {
    if (forkIndex !== undefined) onForkFromMessage?.(forkIndex);
  }, [forkIndex, onForkFromMessage]);
  return (
    <>
      <div
        className={`${marginTop}${stableDeferOffscreenRender ? " thread-render-unit" : ""}`}
        data-thread-display-unit={unitKey}
        data-user-prompt-id={userPromptId}
      >
        {unit.type === "activity" ? (
          <AgentActivityCluster
            messages={unit.messages}
            isTurnStreaming={isTurnStreaming}
            hasBodyBelow={hasBodyBelow}
            turnLatencyMs={unit.turnLatencyMs}
            startedAtMs={unit.startedAtMs}
            cliApps={cliApps}
            mcpPresets={mcpPresets}
            onOpenFilePreview={onOpenFilePreview}
          />
        ) : (
          <MessageBubble
            message={unit.message}
            isTurnStreaming={isTurnStreaming}
            temporary={temporary}
            cliApps={cliApps}
            mcpPresets={mcpPresets}
            slashCommands={slashCommands}
            onOpenFilePreview={onOpenFilePreview}
            onForkFromHere={forkIndex !== undefined ? onForkFromHere : undefined}
          />
        )}
      </div>
      {showForkBoundary ? <ForkBoundaryDivider label={forkBoundaryLabel} /> : null}
    </>
  );
}, threadDisplayUnitPropsEqual);

function threadDisplayUnitPropsEqual(
  previous: ThreadDisplayUnitProps,
  next: ThreadDisplayUnitProps,
): boolean {
  return (
    displayUnitsEqual(previous.unit, next.unit)
    && previous.marginTop === next.marginTop
    && previous.userPromptId === next.userPromptId
    && previous.hasBodyBelow === next.hasBodyBelow
    && previous.deferOffscreenRender === next.deferOffscreenRender
    && previous.isTurnStreaming === next.isTurnStreaming
    && previous.forkIndex === next.forkIndex
    && previous.showForkBoundary === next.showForkBoundary
    && previous.forkBoundaryLabel === next.forkBoundaryLabel
    && previous.temporary === next.temporary
    && previous.cliApps === next.cliApps
    && previous.mcpPresets === next.mcpPresets
    && previous.slashCommands === next.slashCommands
    && previous.onOpenFilePreview === next.onOpenFilePreview
    && previous.onForkFromMessage === next.onForkFromMessage
  );
}

function activeTurnStartIndex(units: DisplayUnit[], activeTurnId: string | null): number {
  if (activeTurnId) {
    const index = units.findIndex((unit) => (
      unit.type === "message"
      && unit.message.role === "user"
      && unit.message.deliveryStatus !== "failed"
      && unit.message.turnId === activeTurnId
    ));
    if (index >= 0) return index;
  }
  for (let i = units.length - 1; i >= 0; i -= 1) {
    const unit = units[i];
    if (
      unit.type === "message"
      && unit.message.role === "user"
      && unit.message.deliveryStatus !== "failed"
    ) return i;
  }
  return -1;
}

function displayUnitsEqual(previous: DisplayUnit, next: DisplayUnit): boolean {
  if (previous.type !== next.type) return false;
  if (previous.type === "message" && next.type === "message") {
    return (
      previous.sourceMessageCount === next.sourceMessageCount
      && shallowMessageEqual(previous.message, next.message)
    );
  }
  if (previous.type !== "activity" || next.type !== "activity") return false;
  return (
    previous.sourceMessageCount === next.sourceMessageCount
    && previous.turnLatencyMs === next.turnLatencyMs
    && previous.startedAtMs === next.startedAtMs
    && previous.messages.length === next.messages.length
    && previous.messages.every((message, index) =>
      shallowMessageEqual(message, next.messages[index]))
  );
}

function shallowMessageEqual(previous: UIMessage, next: UIMessage): boolean {
  if (previous === next) return true;
  const previousKeys = Object.keys(previous) as Array<keyof UIMessage>;
  const nextKeys = Object.keys(next) as Array<keyof UIMessage>;
  return previousKeys.length === nextKeys.length
    && previousKeys.every((key) => previous[key] === next[key]);
}

function unitIndexAfterMessageCount(
  units: DisplayUnit[],
  messageCount: number | null | undefined,
): number | null {
  if (messageCount == null || messageCount <= 0) return null;
  let seen = 0;
  for (let i = 0; i < units.length; i += 1) {
    const unit = units[i];
    seen += unit.sourceMessageCount;
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

function currentActivityClusterIndices(
  units: DisplayUnit[],
  activeTurnId: string | null,
): Set<number> {
  const indices = new Set<number>();
  if (activeTurnId) {
    for (let i = units.length - 1; i >= 0; i -= 1) {
      const unit = units[i];
      if (
        unit.type === "activity"
        && unit.messages.some((message) => message.turnId === activeTurnId)
      ) {
        indices.add(i);
        return indices;
      }
    }
  }

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

export function unitKeysForDisplay(units: DisplayUnit[]): string[] {
  const occurrences = new Map<string, number>();
  return units.map((unit, index) => {
    const base = unitKeyBase(unit, index);
    if (!base.startsWith("turn-") || base.endsWith("-user")) return base;
    const next = (occurrences.get(base) ?? 0) + 1;
    occurrences.set(base, next);
    return `${base}-${next}`;
  });
}

function unitKeyBase(unit: DisplayUnit, index: number): string {
  if (unit.type === "activity") {
    const anchor = unit.messages[0];
    const turnKey = stableTurnMessageKey(anchor, "activity");
    if (turnKey) return turnKey;
    const anchorId = anchor?.id;
    return anchorId != null ? `activity-${anchorId}` : `activity-idx-${index}`;
  }
  const turnKey = stableTurnMessageKey(unit.message);
  if (turnKey) return turnKey;
  return unit.message.id;
}

function stableTurnMessageKey(message: UIMessage | undefined, fallbackPhase?: string): string | null {
  if (!message?.turnId) return null;
  const phase = message.turnPhase ?? fallbackPhase ?? message.kind ?? message.role;
  if (message.role === "user") return `turn-${message.turnId}-user`;
  if (message.kind === "trace") {
    return `turn-${message.turnId}-${phase}-${message.activitySegmentId ?? "activity"}`;
  }
  return `turn-${message.turnId}-${phase}`;
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
