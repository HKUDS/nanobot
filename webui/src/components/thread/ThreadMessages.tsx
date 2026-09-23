import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { MoreHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { MessageBlockMenuActions, MessageBubble } from "@/components/MessageBubble";
import { MessageLinksMenu, useMessageWebLinks } from "@/components/MessageLinksMenu";
import { FallbackResponseSources } from "@/components/ResponseSourceBadge";
import {
  AgentActivityCluster,
  completedActivityDurationMs,
  formatActivityDuration,
} from "@/components/thread/AgentActivityCluster";
import { AssistantSelectionAction } from "@/components/thread/AssistantSelectionAction";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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
  onActivityToggle?: () => void;
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
  onActivityToggle,
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
  const messageBlocks = useMemo(
    () => completedMessageBlocks(
      units,
      unitKeys,
      isStreaming,
      activeTurnId,
      currentTurnStartIndex,
    ),
    [activeTurnId, currentTurnStartIndex, isStreaming, unitKeys, units],
  );
  const [expandedActivityKeys, setExpandedActivityKeys] = useState<Set<string>>(() => new Set());
  const [activeContextBlockKey, setActiveContextBlockKey] = useState<string | null>(null);
  const [openContextBlockKey, setOpenContextBlockKey] = useState<string | null>(null);
  const pointedContextBlockRef = useRef<string | null>(null);
  const setActivityExpanded = useCallback((key: string, expanded: boolean) => {
    onActivityToggle?.();
    setExpandedActivityKeys((current) => {
      if (current.has(key) === expanded) return current;
      const next = new Set(current);
      if (expanded) next.add(key);
      else next.delete(key);
      return next;
    });
  }, [onActivityToggle]);
  const setContextBlockActive = useCallback((key: string | null) => {
    setActiveContextBlockKey((current) => current === key ? current : key);
    setOpenContextBlockKey((current) => current !== null && current !== key ? null : current);
  }, []);
  const setContextBlockPointed = useCallback((key: string | null) => {
    pointedContextBlockRef.current = key;
    setContextBlockActive(key);
  }, [setContextBlockActive]);
  const setContextBlockFocused = useCallback((key: string | null) => {
    setContextBlockActive(key ?? pointedContextBlockRef.current);
  }, [setContextBlockActive]);
  const setContextBlockMenuOpen = useCallback((key: string, open: boolean) => {
    setOpenContextBlockKey((current) => open ? key : current === key ? null : current);
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
        const contextBlockKey = messageBlocks.blockKeys[index]
          ?? (unit.type === "message" && unit.message.role === "user"
            ? `message-block-${unitKeys[index]}`
            : undefined);
        const showBlockContext = messageBlocks.blockIndices.has(index);
        const blockActivity = messageBlocks.activityByBlock.get(index);
        const suppressActivity = messageBlocks.suppressedActivityIndices.has(index);
        const previousVisibleIndex = previousVisibleUnitIndex(
          index,
          messageBlocks.suppressedActivityIndices,
        );
        const marginTop = suppressActivity || previousVisibleIndex < 0
          ? ""
          : marginAfterPrevUnit(units[previousVisibleIndex]);
        const blockActivityExpanded = showBlockContext
          && contextBlockKey !== undefined
          && expandedActivityKeys.has(contextBlockKey);
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
            showBlockContext={showBlockContext}
            blockActivity={blockActivity}
            blockActivityExpanded={blockActivityExpanded}
            contextBlockKey={contextBlockKey}
            contextBlockActive={
              contextBlockKey !== undefined
              && contextBlockKey === (openContextBlockKey ?? activeContextBlockKey)
            }
            contextBlockMenuOpen={contextBlockKey === openContextBlockKey}
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
            onContextBlockActiveChange={setContextBlockPointed}
            onContextBlockFocusChange={setContextBlockFocused}
            onContextBlockMenuOpenChange={setContextBlockMenuOpen}
          />
        );
      })}
      {pendingActivity ? (
        <div className={cn("thread-message-row", units.length > 0 && "mt-5")}>
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
  showBlockContext: boolean;
  blockActivity?: Extract<DisplayUnit, { type: "activity" }>;
  blockActivityExpanded: boolean;
  contextBlockKey?: string;
  contextBlockActive: boolean;
  contextBlockMenuOpen: boolean;
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
  onContextBlockActiveChange: (key: string | null) => void;
  onContextBlockFocusChange: (key: string | null) => void;
  onContextBlockMenuOpenChange: (key: string, open: boolean) => void;
}

interface MessageBlockMenuProps {
  messageRoot: RefObject<HTMLElement>;
  message: UIMessage;
  isTurnStreaming: boolean;
  contextBlockKey: string;
  contextActive: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onContextActiveChange: (key: string | null) => void;
  onForkFromHere?: () => void;
  activity?: {
    label: string;
    expanded: boolean;
    controls: string;
    onToggle: () => void;
  };
}

function MessageBlockMenu({
  messageRoot,
  message,
  isTurnStreaming,
  contextBlockKey,
  contextActive,
  open,
  onOpenChange,
  onContextActiveChange,
  onForkFromHere,
  activity,
}: MessageBlockMenuProps) {
  const { t } = useTranslation();
  const contentRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const links = useMessageWebLinks(messageRoot, open);
  const [linksShown, setLinksShown] = useState(false);
  useEffect(() => { if (!open) setLinksShown(false); }, [open]);
  const [triggerHeight, setTriggerHeight] = useState(28);
  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    if (!open || !trigger) return;
    const measure = () => setTriggerHeight(trigger.getBoundingClientRect().height || 28);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(trigger);
    return () => observer.disconnect();
  }, [open]);
  const contextActiveRef = useRef(contextActive);
  contextActiveRef.current = contextActive;
  const label = t("message.actions");
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          ref={triggerRef}
          type="button"
          data-message-block-menu-trigger
          aria-label={label}
          className={cn(
            "message-block-menu-trigger group touch-target absolute -start-[var(--message-block-trigger-offset)] top-0 z-20",
            "inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-control-size)] items-center justify-center text-muted-foreground/70",
            "transition-[color,opacity] hover:text-foreground focus-visible:outline-none",
            "motion-reduce:transform-none motion-reduce:transition-none",
          )}
        >
          <span
            data-message-block-menu-highlight
            className={cn(
              "inline-flex h-4 w-7 items-center justify-center rounded-full",
              "transition-[background-color,box-shadow,scale]",
              "group-hover:bg-muted/70 group-active:scale-[0.96]",
              "group-focus-visible:ring-2 group-focus-visible:ring-ring",
              "motion-reduce:transform-none motion-reduce:transition-none",
            )}
          >
            <MoreHorizontal className="h-4 w-4" strokeWidth={1.75} aria-hidden />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        ref={contentRef}
        data-message-block-menu
        data-message-context-menu-block={contextBlockKey}
        side="bottom"
        align="end"
        sideOffset={-triggerHeight}
        collisionPadding={12}
        tabIndex={-1}
        aria-label={label}
        onKeyDownCapture={(event) => {
          if (event.key !== "Escape"
            || !(event.target instanceof Node)
            || !event.currentTarget.contains(event.target)) return;
          event.preventDefault();
          event.stopPropagation();
          onOpenChange(false);
        }}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          contentRef.current?.focus({ preventScroll: true });
        }}
        onCloseAutoFocus={(event) => {
          if (!contextActiveRef.current || activity?.expanded) event.preventDefault();
        }}
        onPointerEnter={(event) => {
          if (event.pointerType === "touch") return;
          onContextActiveChange(contextBlockKey);
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "touch") return;
          onContextActiveChange(contextBlockKeyForTarget(event.relatedTarget) ?? null);
        }}
        className={cn(
          "w-max max-w-64 overflow-y-auto outline-none",
          "shadow-[0_2px_10px_rgba(0,0,0,0.08)] dark:shadow-[0_2px_10px_rgba(0,0,0,0.24)]",
        )}
      >
        {linksShown && links.length > 0 ? <MessageLinksMenu links={links}
          onBack={() => { setLinksShown(false); contentRef.current?.focus({ preventScroll: true }); }}
          onClose={() => onOpenChange(false)} /> : <MessageBlockMenuActions
          message={message}
          isTurnStreaming={isTurnStreaming}
          onForkFromHere={onForkFromHere}
          activity={activity}
          onViewLinks={links.length > 0 ? () => setLinksShown(true) : undefined}
        />}
      </PopoverContent>
    </Popover>
  );
}

const ThreadDisplayUnit = memo(function ThreadDisplayUnit({
  unitKey,
  unit,
  marginTop,
  userPromptId,
  hasBodyBelow,
  suppressActivity,
  showBlockContext,
  blockActivity,
  blockActivityExpanded,
  contextBlockKey,
  contextBlockActive,
  contextBlockMenuOpen,
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
  onContextBlockActiveChange,
  onContextBlockFocusChange,
  onContextBlockMenuOpenChange,
}: ThreadDisplayUnitProps) {
  const { t } = useTranslation();
  const elementRef = useRef<HTMLDivElement>(null);
  const activityDetailsId = useId();
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
  const onBlockActivityExpandedChange = useCallback((expanded: boolean) => {
    if (contextBlockKey !== undefined) {
      onActivityExpandedChange(contextBlockKey, expanded);
      window.setTimeout(() => {
        const focusTarget = elementRef.current?.querySelector<HTMLElement>(
          expanded
            ? "[data-contextual-activity-collapse]"
            : "[data-message-block-menu-trigger]",
        );
        focusTarget?.focus({ preventScroll: true });
      }, 0);
    }
  }, [contextBlockKey, onActivityExpandedChange]);
  const activityDurationMs = blockActivity
    ? completedActivityDurationMs(blockActivity.messages, blockActivity.turnLatencyMs)
    : 0;
  const activityLabel = blockActivity
    ? activityDurationMs <= 0
      ? t("message.activityWorked")
      : t("message.activityWorkedFor", {
          duration: formatActivityDuration(activityDurationMs),
        })
    : undefined;
  const onActivityMenuToggle = useCallback(() => {
    onBlockActivityExpandedChange(!blockActivityExpanded);
    if (contextBlockKey !== undefined) {
      onContextBlockMenuOpenChange(contextBlockKey, false);
    }
  }, [
    blockActivityExpanded,
    contextBlockKey,
    onBlockActivityExpandedChange,
    onContextBlockMenuOpenChange,
  ]);
  const blockMenu = unit.type === "message" && contextBlockKey !== undefined ? (
    <MessageBlockMenu
      messageRoot={elementRef}
      message={unit.message}
      isTurnStreaming={isTurnStreaming}
      contextBlockKey={contextBlockKey}
      contextActive={contextBlockActive}
      open={contextBlockMenuOpen}
      onOpenChange={(open) => onContextBlockMenuOpenChange(contextBlockKey, open)}
      onContextActiveChange={onContextBlockActiveChange}
      onForkFromHere={forkIndex !== undefined ? onForkFromHere : undefined}
      activity={activityLabel ? {
        label: activityLabel,
        expanded: blockActivityExpanded,
        controls: activityDetailsId,
        onToggle: onActivityMenuToggle,
      } : undefined}
    />
  ) : null;
  return (
    <>
      <div
        ref={elementRef}
        className={cn(
          "thread-message-row",
          marginTop,
          contextBlockKey !== undefined && "message-context-hit-area relative",
        )}
        style={retainContent ? undefined : { height: heightRef.current }}
        onPointerDownCapture={() => {
          setInteracted(true);
          onContextBlockActiveChange(contextBlockKey ?? null);
        }}
        data-thread-display-unit={unitKey}
        data-user-prompt-id={userPromptId}
        data-message-context-block={contextBlockKey}
        data-context-block-active={contextBlockActive || undefined}
        data-message-context-menu-open={contextBlockMenuOpen || undefined}
        onPointerEnter={(event) => {
          if (event.pointerType === "touch") return;
          onContextBlockActiveChange(contextBlockKey ?? null);
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "touch") return;
          onContextBlockActiveChange(contextBlockKeyForTarget(event.relatedTarget) ?? null);
        }}
        onFocusCapture={() => {
          setInteracted(true);
          onContextBlockFocusChange(contextBlockKey ?? null);
        }}
        onBlurCapture={(event) => {
          onContextBlockFocusChange(contextBlockKeyForTarget(event.relatedTarget) ?? null);
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
          <div className={unit.message.role === "assistant" ? "relative" : undefined}>
            {unit.message.role === "assistant" ? blockMenu : null}
            {showBlockContext && blockActivity ? (
              <div className={blockActivityExpanded ? "mb-2" : undefined}>
                <AgentActivityCluster
                  messages={blockActivity.messages}
                  isTurnStreaming={false}
                  retryStatus={null}
                  hasBodyBelow={false}
                  expanded={blockActivityExpanded}
                  onExpandedChange={onBlockActivityExpandedChange}
                  hideHeader
                  detailsId={activityDetailsId}
                  turnLatencyMs={blockActivity.turnLatencyMs}
                  startedAtMs={blockActivity.startedAtMs}
                  cliApps={cliApps}
                  mcpPresets={mcpPresets}
                  traceDetailScope={traceDetailScope}
                  onLoadTraceDetails={onLoadTraceDetails}
                  onOpenFilePreview={onOpenFilePreview}
                />
              </div>
            ) : null}
            <MessageBubble
              message={unit.message}
              temporary={temporary}
              cliApps={cliApps}
              mcpPresets={mcpPresets}
              slashCommands={slashCommands}
              onOpenFilePreview={onOpenFilePreview}
              contextMenu={unit.message.role === "user" ? blockMenu : undefined}
            />
            {unit.message.role === "assistant"
            && unit.message.kind !== "compaction"
            && contextBlockKey === undefined ? (
              <FallbackResponseSources
                sources={unit.message.responseSources}
                className="relative mt-0.5 text-muted-foreground"
              />
            ) : null}
          </div>
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
    && previous.showBlockContext === next.showBlockContext
    && previous.blockActivity === next.blockActivity
    && previous.blockActivityExpanded === next.blockActivityExpanded
    && previous.contextBlockKey === next.contextBlockKey
    && previous.contextBlockActive === next.contextBlockActive
    && previous.contextBlockMenuOpen === next.contextBlockMenuOpen
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
    && previous.onContextBlockActiveChange === next.onContextBlockActiveChange
    && previous.onContextBlockFocusChange === next.onContextBlockFocusChange
    && previous.onContextBlockMenuOpenChange === next.onContextBlockMenuOpenChange
  );
}

function contextBlockKeyForTarget(target: EventTarget | null): string | undefined {
  if (!(target instanceof Element)) return undefined;
  const owner = target.closest<HTMLElement>(
    "[data-message-context-block], [data-message-context-menu-block]",
  );
  return owner?.dataset.messageContextBlock ?? owner?.dataset.messageContextMenuBlock;
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
    <div className="thread-message-row my-5 flex items-center gap-3 text-[11px] text-muted-foreground/80">
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
    return "mt-5";
  }
  return "mt-5";
}

interface CompletedMessageBlocks {
  blockKeys: Array<string | undefined>;
  blockIndices: Set<number>;
  suppressedActivityIndices: Set<number>;
  activityByBlock: Map<number, Extract<DisplayUnit, { type: "activity" }>>;
}

function completedMessageBlocks(
  units: DisplayUnit[],
  unitKeys: string[],
  isStreaming: boolean,
  activeTurnId: string | null,
  currentTurnStartIndex: number,
): CompletedMessageBlocks {
  const result: CompletedMessageBlocks = {
    blockKeys: new Array<string | undefined>(units.length),
    blockIndices: new Set<number>(),
    suppressedActivityIndices: new Set<number>(),
    activityByBlock: new Map(),
  };
  let groupStart = 0;
  let groupTurnId: string | undefined;

  const flushGroup = (end: number) => {
    if (groupStart >= end) return;
    const indices = Array.from({ length: end - groupStart }, (_, offset) => groupStart + offset);
    const groupIsStreaming = isStreaming && indices.some((index) => {
      const unit = units[index];
      const turnId = displayUnitTurnId(unit);
      if (activeTurnId && turnId) return turnId === activeTurnId;
      return index > currentTurnStartIndex;
    });
    if (groupIsStreaming) return;

    const blockIndices = indices.filter((index) => {
      const unit = units[index];
      return unit.type === "message"
        && unit.message.role === "assistant"
        && unit.message.kind !== "compaction";
    });
    for (const index of blockIndices) {
      result.blockIndices.add(index);
      result.blockKeys[index] = `message-block-${unitKeys[index]}`;
    }

    const activityByBlock = new Map<number, Array<Extract<DisplayUnit, { type: "activity" }>>>();
    for (const index of indices) {
      const unit = units[index];
      if (unit.type !== "activity") continue;
      const blockIndex = blockIndices.find((candidate) => candidate > index) ?? blockIndices.at(-1);
      if (blockIndex === undefined) continue;
      result.suppressedActivityIndices.add(index);
      const activityUnits = activityByBlock.get(blockIndex) ?? [];
      activityUnits.push(unit);
      activityByBlock.set(blockIndex, activityUnits);
    }
    for (const [blockIndex, activityUnits] of activityByBlock) {
      result.activityByBlock.set(blockIndex, mergeActivityUnits(activityUnits));
    }
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

function mergeActivityUnits(
  units: Array<Extract<DisplayUnit, { type: "activity" }>>,
): Extract<DisplayUnit, { type: "activity" }> {
  return {
    type: "activity",
    messages: units.flatMap((unit) => unit.messages),
    sourceMessageCount: units.reduce((count, unit) => count + unit.sourceMessageCount, 0),
    turnLatencyMs: [...units].reverse().find((unit) => unit.turnLatencyMs !== undefined)
      ?.turnLatencyMs,
    startedAtMs: units.find((unit) => unit.startedAtMs !== undefined)?.startedAtMs,
  };
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
