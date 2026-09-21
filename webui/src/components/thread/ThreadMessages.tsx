import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AssistantMessageActions, MessageBubble } from "@/components/MessageBubble";
import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { AssistantSelectionAction } from "@/components/thread/AssistantSelectionAction";
import { projectActivityTimeline, type TurnUnit } from "@/lib/activity-timeline";
import { cn } from "@/lib/utils";
import type { CliAppInfo, McpPresetInfo, RetryStatus, SlashCommand, UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  temporary?: boolean;
  /** When true, agent turn still in flight — keeps activity timeline expanded. */
  isStreaming?: boolean;
  activeTurnId?: string | null;
  /** Optimistic or canonical active-turn start, in unix seconds. */
  runStartedAt?: number | null;
  retryStatus?: RetryStatus | null;
  hiddenUserMessageCount?: number;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  slashCommands?: SlashCommand[];
  forkBoundaryMessageCount?: number | null;
  traceDetailScope?: string | null;
  onLoadTraceDetails?: (refs: string[]) => void | Promise<void>;
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
  retryStatus = null,
  hiddenUserMessageCount = 0,
  cliApps = [],
  mcpPresets = [],
  slashCommands = [],
  forkBoundaryMessageCount = null,
  traceDetailScope = null,
  onLoadTraceDetails,
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
    && (retryStatus !== null || !pendingTurn.hasVisibleOutput)
  ) ? pendingTurn : null;
  const currentTurnStartIndex = isStreaming
    ? activeTurnStartIndex(units, activeTurnId)
    : units.length;
  const unitKeys = useMemo(() => unitKeysForDisplay(units), [units]);
  const turnFooters = useMemo(
    () => completedTurnFooters(
      units,
      unitKeys,
      isStreaming,
      activeTurnId,
      currentTurnStartIndex,
    ),
    [activeTurnId, currentTurnStartIndex, isStreaming, unitKeys, units],
  );
  const [expandedActivityKeys, setExpandedActivityKeys] = useState<Set<string>>(() => new Set());
  const [activeContextGroupKey, setActiveContextGroupKey] = useState<string | null>(null);
  const setActivityExpanded = useCallback((key: string, expanded: boolean) => {
    setExpandedActivityKeys((current) => {
      if (current.has(key) === expanded) return current;
      const next = new Set(current);
      if (expanded) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);
  const setContextGroupActive = useCallback((key: string | null) => {
    setActiveContextGroupKey((current) => current === key ? current : key);
  }, []);
  let nextUserIndex = hiddenUserMessageCount;

  return (
    <div ref={messageListRef} className="flex w-full flex-col">
      <AssistantSelectionAction
        containerRef={messageListRef}
        onQuoteSelection={onQuoteSelection}
      />
      {units.map((unit, index) => {
        const next = units[index + 1];
        const hasBodyBelow =
          unit.type === "activity"
          && next?.type === "message"
          && next.message.role === "assistant";
        const contextGroupKey = turnFooters.contextKeys[index];
        const showTurnFooter = turnFooters.ownerIndices.has(index);
        const turnFooterActivity = turnFooters.activityByOwner.get(index);
        const suppressActivity = turnFooters.suppressedActivityIndices.has(index);
        const previousVisibleIndex = previousVisibleUnitIndex(
          index,
          turnFooters.suppressedActivityIndices,
        );
        const marginTop = suppressActivity || previousVisibleIndex < 0
          ? ""
          : marginAfterPrevUnit(
              units[previousVisibleIndex],
              turnFooters.ownerIndices.has(previousVisibleIndex),
              showTurnFooter && turnFooterActivity !== undefined,
            );
        const turnFooterExpanded = showTurnFooter
          && contextGroupKey !== undefined
          && expandedActivityKeys.has(contextGroupKey);
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
        const unitTurnStreaming = unit.type === "activity"
          ? liveActivityClusterIndices.has(index)
          : isStreaming && (
              unit.message.turnId && activeTurnId !== null
                ? unit.message.turnId === activeTurnId
                : index > currentTurnStartIndex
            );
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
            suppressActivity={suppressActivity}
            showTurnFooter={showTurnFooter}
            turnFooterActivity={turnFooterActivity}
            turnFooterExpanded={turnFooterExpanded}
            contextGroupKey={contextGroupKey}
            contextGroupActive={
              contextGroupKey !== undefined && contextGroupKey === activeContextGroupKey
            }
            deferOffscreenRender={deferOffscreenRender}
            isTurnStreaming={unitTurnStreaming}
            retryStatus={
              unit.type === "activity" && liveActivityClusterIndices.has(index)
                ? retryStatus
                : null
            }
            forkIndex={forkIndex}
            showForkBoundary={index === forkBoundaryAfterUnitIndex}
            forkBoundaryLabel={t("thread.forkedFromHistory")}
            temporary={temporary}
            cliApps={cliApps}
            mcpPresets={mcpPresets}
            slashCommands={slashCommands}
            traceDetailScope={traceDetailScope}
            onLoadTraceDetails={onLoadTraceDetails}
            onOpenFilePreview={onOpenFilePreview}
            onForkFromMessage={onForkFromMessage}
            onActivityExpandedChange={setActivityExpanded}
            onContextGroupActiveChange={setContextGroupActive}
          />
        );
      })}
      {pendingActivity ? (
        <div className={cn(units.length > 0 && "mt-5")}>
          <AgentActivityCluster
            messages={[]}
            isTurnStreaming
            hasBodyBelow={false}
            retryStatus={retryStatus}
            startedAtMs={
              // Match the activity timeline's prompt-based clock across the first output.
              pendingActivity.startedAtMs ?? (runStartedAt != null ? runStartedAt * 1000 : undefined)
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
  suppressActivity: boolean;
  showTurnFooter: boolean;
  turnFooterActivity?: Extract<DisplayUnit, { type: "activity" }>;
  turnFooterExpanded: boolean;
  contextGroupKey?: string;
  contextGroupActive: boolean;
  deferOffscreenRender: boolean;
  isTurnStreaming: boolean;
  retryStatus: RetryStatus | null;
  forkIndex?: number;
  showForkBoundary: boolean;
  forkBoundaryLabel: string;
  temporary: boolean;
  cliApps: CliAppInfo[];
  mcpPresets: McpPresetInfo[];
  slashCommands: SlashCommand[];
  traceDetailScope: string | null;
  onLoadTraceDetails?: (refs: string[]) => void | Promise<void>;
  onOpenFilePreview?: (path: string) => void;
  onForkFromMessage?: (beforeUserIndex: number) => void;
  onActivityExpandedChange: (key: string, expanded: boolean) => void;
  onContextGroupActiveChange: (key: string | null) => void;
}

const ThreadDisplayUnit = memo(function ThreadDisplayUnit({
  unitKey,
  unit,
  marginTop,
  userPromptId,
  hasBodyBelow,
  suppressActivity,
  showTurnFooter,
  turnFooterActivity,
  turnFooterExpanded,
  contextGroupKey,
  contextGroupActive,
  deferOffscreenRender,
  isTurnStreaming,
  retryStatus,
  forkIndex,
  showForkBoundary,
  forkBoundaryLabel,
  temporary,
  cliApps,
  mcpPresets,
  slashCommands,
  traceDetailScope,
  onLoadTraceDetails,
  onOpenFilePreview,
  onForkFromMessage,
  onActivityExpandedChange,
  onContextGroupActiveChange,
}: ThreadDisplayUnitProps) {
  const elementRef = useRef<HTMLDivElement>(null);
  const heightRef = useRef(0);
  const [nearViewport, setNearViewport] = useState(true);
  const [interacted, setInteracted] = useState(false);
  const retainContent = !deferOffscreenRender || interacted || nearViewport;
  useEffect(() => {
    const element = elementRef.current;
    if (!element || !deferOffscreenRender || interacted || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry) return;
      if (!entry.isIntersecting) {
        const height = element.getBoundingClientRect().height;
        if (height <= 0) return;
        heightRef.current = height;
      }
      setNearViewport(entry.isIntersecting);
    }, { rootMargin: "1000px 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [deferOffscreenRender, interacted]);
  const onForkFromHere = useCallback(() => {
    if (forkIndex !== undefined) onForkFromMessage?.(forkIndex);
  }, [forkIndex, onForkFromMessage]);
  const onTurnFooterExpandedChange = useCallback((expanded: boolean) => {
    if (contextGroupKey !== undefined) {
      onActivityExpandedChange(contextGroupKey, expanded);
    }
  }, [contextGroupKey, onActivityExpandedChange]);
  const turnContextPinned = unit.type === "message"
    && !!unit.message.responseSources?.some((source) => source.fallback === true);
  const turnActions = unit.type === "message" && showTurnFooter ? (
    <AssistantMessageActions
      message={unit.message}
      isTurnStreaming={isTurnStreaming}
      onForkFromHere={forkIndex !== undefined ? onForkFromHere : undefined}
      inline
    />
  ) : null;
  return (
    <>
      <div
        ref={elementRef}
        className={marginTop}
        style={retainContent ? undefined : { height: heightRef.current }}
        onPointerDownCapture={(event) => {
          setInteracted(true);
          if (event.pointerType === "touch") {
            onContextGroupActiveChange(contextGroupKey ?? null);
          }
        }}
        data-thread-display-unit={unitKey}
        data-user-prompt-id={userPromptId}
        data-message-context-group={contextGroupKey}
        data-context-group-active={contextGroupActive || undefined}
        onPointerEnter={(event) => {
          if (event.pointerType === "touch") return;
          onContextGroupActiveChange(contextGroupKey ?? null);
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "touch") return;
          onContextGroupActiveChange(contextGroupKeyForTarget(event.relatedTarget) ?? null);
        }}
        onFocusCapture={() => {
          setInteracted(true);
          onContextGroupActiveChange(contextGroupKey ?? null);
        }}
        onBlurCapture={(event) => {
          onContextGroupActiveChange(contextGroupKeyForTarget(event.relatedTarget) ?? null);
        }}
      >
        {retainContent ? unit.type === "activity" ? (
          suppressActivity ? null : (
            <AgentActivityCluster
              messages={unit.messages}
              isTurnStreaming={isTurnStreaming}
              retryStatus={retryStatus}
              hasBodyBelow={hasBodyBelow}
              turnLatencyMs={unit.turnLatencyMs}
              startedAtMs={unit.startedAtMs}
              cliApps={cliApps}
              mcpPresets={mcpPresets}
              traceDetailScope={traceDetailScope}
              onLoadTraceDetails={onLoadTraceDetails}
              onOpenFilePreview={onOpenFilePreview}
            />
          )
        ) : (
          <>
            {showTurnFooter && turnFooterActivity ? (
              <AgentActivityCluster
                messages={turnFooterActivity.messages}
                isTurnStreaming={false}
                retryStatus={null}
                hasBodyBelow={false}
                expanded={turnFooterExpanded}
                onExpandedChange={onTurnFooterExpandedChange}
                turnLatencyMs={turnFooterActivity.turnLatencyMs}
                startedAtMs={turnFooterActivity.startedAtMs}
                cliApps={cliApps}
                mcpPresets={mcpPresets}
                traceDetailScope={traceDetailScope}
                onLoadTraceDetails={onLoadTraceDetails}
                onOpenFilePreview={onOpenFilePreview}
              />
            ) : null}
            <MessageBubble
              message={unit.message}
              isTurnStreaming={isTurnStreaming}
              temporary={temporary}
              cliApps={cliApps}
              mcpPresets={mcpPresets}
              slashCommands={slashCommands}
              onOpenFilePreview={onOpenFilePreview}
              onForkFromHere={forkIndex !== undefined ? onForkFromHere : undefined}
              showAssistantContextActions={contextGroupKey === undefined}
            />
            {showTurnFooter ? (
              <div
                data-turn-context-rail
                data-turn-context-pinned={turnContextPinned || undefined}
                className="flex min-h-5 max-w-[45rem] items-center"
              >
                {turnActions}
              </div>
            ) : null}
          </>
        ) : null}
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
    && previous.suppressActivity === next.suppressActivity
    && previous.showTurnFooter === next.showTurnFooter
    && previous.turnFooterActivity === next.turnFooterActivity
    && previous.turnFooterExpanded === next.turnFooterExpanded
    && previous.contextGroupKey === next.contextGroupKey
    && previous.contextGroupActive === next.contextGroupActive
    && previous.deferOffscreenRender === next.deferOffscreenRender
    && previous.isTurnStreaming === next.isTurnStreaming
    && previous.retryStatus === next.retryStatus
    && previous.forkIndex === next.forkIndex
    && previous.showForkBoundary === next.showForkBoundary
    && previous.forkBoundaryLabel === next.forkBoundaryLabel
    && previous.temporary === next.temporary
    && previous.cliApps === next.cliApps
    && previous.mcpPresets === next.mcpPresets
    && previous.slashCommands === next.slashCommands
    && previous.traceDetailScope === next.traceDetailScope
    && previous.onLoadTraceDetails === next.onLoadTraceDetails
    && previous.onOpenFilePreview === next.onOpenFilePreview
    && previous.onForkFromMessage === next.onForkFromMessage
    && previous.onActivityExpandedChange === next.onActivityExpandedChange
    && previous.onContextGroupActiveChange === next.onContextGroupActiveChange
  );
}

function contextGroupKeyForTarget(target: EventTarget | null): string | undefined {
  return target instanceof Element
    ? target.closest<HTMLElement>("[data-message-context-group]")?.dataset.messageContextGroup
    : undefined;
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

function marginAfterPrevUnit(
  prev: DisplayUnit,
  hasTurnFooter: boolean,
  currentHasActivityHeader: boolean,
): string {
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
  if (p.role === "assistant" && !p.isStreaming && p.content.trim().length > 0) {
    // The lower action row or the next answer's upper activity row supplies
    // the normal inter-message rhythm without stacking extra whitespace.
    return hasTurnFooter || currentHasActivityHeader ? "" : "mt-5";
  }
  return "mt-5";
}

interface CompletedTurnFooters {
  contextKeys: Array<string | undefined>;
  ownerIndices: Set<number>;
  suppressedActivityIndices: Set<number>;
  activityByOwner: Map<number, Extract<DisplayUnit, { type: "activity" }>>;
}

function completedTurnFooters(
  units: DisplayUnit[],
  unitKeys: string[],
  isStreaming: boolean,
  activeTurnId: string | null,
  currentTurnStartIndex: number,
): CompletedTurnFooters {
  const result: CompletedTurnFooters = {
    contextKeys: new Array<string | undefined>(units.length),
    ownerIndices: new Set<number>(),
    suppressedActivityIndices: new Set<number>(),
    activityByOwner: new Map(),
  };
  let groupStart = 0;
  let groupTurnId: string | undefined;

  const flushGroup = (end: number) => {
    if (groupStart >= end) return;
    const indices = Array.from({ length: end - groupStart }, (_, offset) => groupStart + offset);
    const ownerIndex = [...indices].reverse().find((index) => {
      const unit = units[index];
      return unit.type === "message"
        && unit.message.role === "assistant"
        && unit.message.kind !== "compaction";
    });
    if (ownerIndex === undefined) return;

    const groupIsStreaming = isStreaming && indices.some((index) => {
      const unit = units[index];
      const turnId = displayUnitTurnId(unit);
      if (activeTurnId && turnId) return turnId === activeTurnId;
      return index > currentTurnStartIndex;
    });
    if (groupIsStreaming) return;

    const contextKey = `turn-context-${groupTurnId ?? unitKeys[ownerIndex]}`;
    result.ownerIndices.add(ownerIndex);
    for (const index of indices) {
      const unit = units[index];
      if (unit.type === "activity" || (
        unit.type === "message"
        && unit.message.role === "assistant"
        && unit.message.kind !== "compaction"
      )) {
        result.contextKeys[index] = contextKey;
      }
    }

    const activityUnits = indices
      .map((index) => ({ index, unit: units[index] }))
      .filter((entry): entry is {
        index: number;
        unit: Extract<DisplayUnit, { type: "activity" }>;
      } => entry.unit.type === "activity");
    if (!activityUnits.length) return;
    for (const { index } of activityUnits) result.suppressedActivityIndices.add(index);
    result.activityByOwner.set(ownerIndex, {
      type: "activity",
      messages: activityUnits.flatMap(({ unit }) => unit.messages),
      sourceMessageCount: activityUnits.reduce(
        (count, { unit }) => count + unit.sourceMessageCount,
        0,
      ),
      turnLatencyMs: [...activityUnits].reverse().find(({ unit }) => unit.turnLatencyMs !== undefined)
        ?.unit.turnLatencyMs,
      startedAtMs: activityUnits.find(({ unit }) => unit.startedAtMs !== undefined)
        ?.unit.startedAtMs,
    });
  };

  for (let index = 0; index < units.length; index += 1) {
    const unit = units[index];
    if (unit.type === "message" && unit.message.role === "user") {
      flushGroup(index);
      groupStart = index + 1;
      groupTurnId = unit.message.turnId;
      continue;
    }
    const turnId = displayUnitTurnId(unit);
    if (turnId && groupTurnId && turnId !== groupTurnId) {
      flushGroup(index);
      groupStart = index;
      groupTurnId = turnId;
    } else if (turnId && !groupTurnId) {
      groupTurnId = turnId;
    }
  }
  flushGroup(units.length);
  return result;
}

function displayUnitTurnId(unit: DisplayUnit): string | undefined {
  return unit.type === "activity"
    ? unit.messages.find((message) => message.turnId)?.turnId
    : unit.message.turnId;
}

function previousVisibleUnitIndex(
  index: number,
  suppressedActivityIndices: ReadonlySet<number>,
): number {
  for (let previous = index - 1; previous >= 0; previous -= 1) {
    if (!suppressedActivityIndices.has(previous)) return previous;
  }
  return -1;
}
