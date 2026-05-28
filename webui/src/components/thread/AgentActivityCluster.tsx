import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Layers,
  Search,
  Server,
  Terminal,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { cliAppInitials, mcpPresetInitials } from "@/components/CliAppMentionText";
import { FileReferenceChip } from "@/components/FileReferenceChip";
import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import { StreamingLabelSheen } from "@/components/MessageBubble";
import { faviconUrls, logoFallbackUrls } from "@/lib/provider-brand";
import { formatToolCallTrace } from "@/lib/tool-traces";
import { cn } from "@/lib/utils";
import type { CliAppInfo, McpPresetInfo, ToolProgressEvent, UIFileEdit, UIMessage } from "@/lib/types";

/** Scrollport height for the Cursor-style “live trace” strip (tailwind spacing). */
const CLUSTER_SCROLL_MAX_CLASS = "max-h-52";
const ACTIVITY_SCROLL_NEAR_BOTTOM_PX = 24;

export function isReasoningOnlyAssistant(m: UIMessage): boolean {
  if (m.role !== "assistant" || m.kind === "trace") return false;
  if (m.content.trim().length > 0) return false;
  return !!(m.reasoning?.length || m.reasoningStreaming || m.isStreaming);
}

export function isAgentActivityMember(m: UIMessage): boolean {
  return isReasoningOnlyAssistant(m) || m.kind === "trace";
}

interface ActivityCounts {
  reasoningSteps: number;
  toolCalls: number;
  cliCount: number;
  mcpCount: number;
  fileCount: number;
  added: number;
  deleted: number;
  hasDiffStats: boolean;
  hasEditingFiles: boolean;
  hasFailedFiles: boolean;
  hasDeletedFiles: boolean;
  primaryFilePath?: string;
  primaryFileTooltipPath?: string;
  primaryCliName?: string;
  primaryCliStatus?: CliRunStatus;
  primaryMcpName?: string;
  primaryMcpDisplayName?: string;
  primaryMcpStatus?: McpRunStatus;
}

interface FileEditSummary {
  key: string;
  path: string;
  absolute_path?: string;
  added: number;
  deleted: number;
  approximate: boolean;
  binary: boolean;
  status: UIFileEdit["status"];
  operation?: UIFileEdit["operation"];
  pending: boolean;
  error?: string;
}

interface CliRunSummary {
  key: string;
  name: string;
  args: string[];
  json: boolean;
  workingDir?: string;
  status: CliRunStatus;
  error?: string;
}

type CliRunStatus = "running" | "done" | "error";
type McpRunStatus = "running" | "done" | "error";

interface McpRunSummary {
  key: string;
  presetName: string;
  displayName: string;
  toolName: string;
  argsPreview: string;
  status: McpRunStatus;
  error?: string;
}

function countActivity(
  messages: UIMessage[],
  fileEdits: FileEditSummary[],
  cliRuns: CliRunSummary[],
  mcpRuns: McpRunSummary[],
): ActivityCounts {
  let reasoningSteps = 0;
  let toolCalls = 0;
  const cliCount = cliRuns.length;
  const mcpCount = mcpRuns.length;
  const primaryCli = cliRuns[cliRuns.length - 1];
  const primaryCliName = primaryCli?.name;
  const primaryCliStatus = primaryCli?.status;
  const primaryMcp = mcpRuns[mcpRuns.length - 1];
  for (const m of messages) {
    if (isReasoningOnlyAssistant(m)) {
      reasoningSteps += 1;
      continue;
    }
    if (m.kind === "trace") {
      const lines = traceLines(m);
      for (const line of lines) {
        if (!isCliRunTraceLine(line) && !isMcpRunTraceLine(line)) {
          toolCalls += 1;
        }
      }
    }
  }
  let added = 0;
  let deleted = 0;
  let hasDiffStats = false;
  let hasEditingFiles = false;
  let failedFileCount = 0;
  let deletedFileCount = 0;
  let primaryFilePath: string | undefined;
  let primaryFileTooltipPath: string | undefined;
  for (const edit of fileEdits) {
    primaryFilePath = edit.path;
    primaryFileTooltipPath = edit.absolute_path || edit.path;
    if (edit.status === "editing") {
      hasEditingFiles = true;
    }
    if (edit.status === "error") {
      failedFileCount += 1;
    }
    if (edit.operation === "delete") {
      deletedFileCount += 1;
    }
    if (edit.status === "error" || edit.binary) {
      continue;
    }
    if (!hasVisibleDiffStats(edit)) {
      continue;
    }
    hasDiffStats = true;
    added += edit.added;
    deleted += edit.deleted;
  }
  return {
    reasoningSteps,
    toolCalls,
    cliCount,
    mcpCount,
    fileCount: fileEdits.length,
    added,
    deleted,
    hasDiffStats,
    hasEditingFiles,
    hasFailedFiles: fileEdits.length > 0 && failedFileCount === fileEdits.length,
    hasDeletedFiles: fileEdits.length > 0 && deletedFileCount === fileEdits.length,
    primaryFilePath,
    primaryFileTooltipPath,
    primaryCliName,
    primaryCliStatus,
    primaryMcpName: primaryMcp?.presetName,
    primaryMcpDisplayName: primaryMcp?.displayName,
    primaryMcpStatus: primaryMcp?.status,
  };
}

interface AgentActivityClusterProps {
  messages: UIMessage[];
  /** True while the session turn is still running (drives “Working…” copy + header sheen). */
  isTurnStreaming: boolean;
  hasBodyBelow: boolean;
  /** Persisted end-to-end turn latency from the assistant answer, used for history replay. */
  turnLatencyMs?: number;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
}

/**
 * Outer fold wrapping interleaved reasoning-only assistant rows and tool-trace rows.
 * Fixed max height with inner scroll; each block keeps its own small collapsible (reasoning / tools).
 */
export function AgentActivityCluster({
  messages,
  isTurnStreaming,
  hasBodyBelow,
  turnLatencyMs,
  cliApps = [],
  mcpPresets = [],
}: AgentActivityClusterProps) {
  const { t } = useTranslation();
  const fileEdits = useMemo(
    () => summarizeFileEdits(collectFileEdits(messages), isTurnStreaming),
    [messages, isTurnStreaming],
  );
  const cliRuns = useMemo(() => collectCliRuns(messages), [messages]);
  const mcpRuns = useMemo(() => collectMcpRuns(messages), [messages]);
  const cliAppsByName = useMemo(
    () => new Map(cliApps.map((app) => [app.name.toLowerCase(), app])),
    [cliApps],
  );
  const mcpPresetsByName = useMemo(
    () => new Map(mcpPresets.map((preset) => [preset.name.toLowerCase(), preset])),
    [mcpPresets],
  );
  const {
    reasoningSteps,
    toolCalls,
    cliCount,
    mcpCount,
    fileCount,
    added,
    deleted,
    hasDiffStats,
    hasEditingFiles,
    hasFailedFiles,
    hasDeletedFiles,
    primaryFilePath,
    primaryFileTooltipPath,
    primaryCliName,
    primaryCliStatus,
    primaryMcpDisplayName,
    primaryMcpStatus,
  } = countActivity(messages, fileEdits, cliRuns, mcpRuns);
  const hasPendingFileEdit = fileEdits.some((edit) => edit.pending);

  const [userToggledOuter, setUserToggledOuter] = useState(false);
  const [outerOpenLocal, setOuterOpenLocal] = useState(false);
  const [completionHoldOpen, setCompletionHoldOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const activityScrollRef = useRef<HTMLDivElement>(null);
  const activityContentRef = useRef<HTMLDivElement>(null);
  const autoFollowActivityRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);
  const wasTurnStreamingRef = useRef(isTurnStreaming);
  const wasTurnStreaming = wasTurnStreamingRef.current;
  /** Live work stays open; completed work briefly shows the done state, then tucks away. */
  const outerExpanded = userToggledOuter
    ? outerOpenLocal
    : isTurnStreaming || completionHoldOpen || (wasTurnStreaming && !isTurnStreaming);

  const hasLiveEditingFiles = isTurnStreaming && hasEditingFiles;
  const singleFilePath = fileCount === 1 ? primaryFilePath : undefined;
  const singleFileTooltipPath = fileCount === 1 ? primaryFileTooltipPath : undefined;
  const hasVisibleActivity = reasoningSteps > 0 || toolCalls > 0 || cliCount > 0 || mcpCount > 0 || fileCount > 0;
  const hasOnlyFileActivity = fileCount > 0 && messages.every(messageHasOnlyFileActivity);
  const durationMs = activityDurationMs(messages, isTurnStreaming, now, turnLatencyMs);
  const activityDuration = formatActivityDuration(durationMs);
  const thoughtLabel = isTurnStreaming
    ? t("message.activityThinkingFor", {
        duration: activityDuration,
        defaultValue: "Thinking for {{duration}}",
      })
    : durationMs <= 0
      ? t("message.activityThought", { defaultValue: "Thought" })
    : t("message.activityThoughtFor", {
        duration: activityDuration,
        defaultValue: "Thought for {{duration}}",
      });

  const fileActivitySummary = fileCount > 0
    ? hasPendingFileEdit && !singleFilePath
      ? t("message.fileActivityPreparing", { defaultValue: "Preparing edit…" })
      : singleFilePath
      ? t(fileActivitySummaryKey(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles), {
          file: shortFileName(singleFilePath),
          defaultValue: `${fileActivityVerb(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles)} {{file}}`,
        })
      : t(fileActivityManySummaryKey(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles), {
          count: fileCount,
          defaultValue: `${fileActivityVerb(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles)} {{count}} files`,
        })
    : "";

  const cliActivitySummary = cliCount > 0
    ? cliCount === 1 && primaryCliName
      ? t(cliActivitySummaryKey(primaryCliStatus, isTurnStreaming), {
          name: primaryCliName,
          defaultValue: cliActivitySummaryDefault(primaryCliStatus, isTurnStreaming),
        })
      : t(cliActivityManySummaryKey(cliRuns, isTurnStreaming), {
          count: cliCount,
          defaultValue: cliActivityManySummaryDefault(cliRuns, isTurnStreaming),
        })
    : "";

  const mcpActivitySummary = mcpCount > 0
    ? mcpCount === 1 && primaryMcpDisplayName
      ? t(mcpActivitySummaryKey(primaryMcpStatus, isTurnStreaming), {
          name: primaryMcpDisplayName,
          defaultValue: mcpActivitySummaryDefault(primaryMcpStatus, isTurnStreaming),
        })
      : t(mcpActivityManySummaryKey(mcpRuns, isTurnStreaming), {
          count: mcpCount,
          defaultValue: mcpActivityManySummaryDefault(mcpRuns, isTurnStreaming),
        })
    : "";

  const summary = fileCount > 0
    ? fileActivitySummary
    : cliCount > 0
      ? cliActivitySummary
    : mcpCount > 0
      ? mcpActivitySummary
    : isTurnStreaming
      ? reasoningSteps > 0
        ? t("message.agentActivityLiveSummary", {
            reasoning: reasoningSteps,
            tools: toolCalls,
            defaultValue: "Working… · {{reasoning}} steps · {{tools}} tool calls",
          })
        : toolCalls === 0 && fileCount > 0
          ? t("message.agentActivityLiveFilesOnly", { defaultValue: "Working…" })
        : t("message.agentActivityLiveToolsOnly", {
            tools: toolCalls,
            defaultValue: "Working… · {{tools}} tool calls",
          })
      : reasoningSteps > 0
        ? t("message.agentActivitySummary", {
            reasoning: reasoningSteps,
            tools: toolCalls,
            defaultValue: "{{reasoning}} steps · {{tools}} tool calls",
          })
        : toolCalls === 0 && fileCount > 0
          ? t("message.agentActivityFilesOnly", { defaultValue: "File changes" })
        : t("message.agentActivityToolsOnly", {
            tools: toolCalls,
            defaultValue: "{{tools}} tool calls",
          });

  const cancelActivityScrollFrame = useCallback(() => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = null;
    }
  }, []);

  const scrollActivityToBottom = useCallback(() => {
    const el = activityScrollRef.current;
    if (!el) return;
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight);
  }, []);

  const scheduleActivityScrollToBottom = useCallback(() => {
    cancelActivityScrollFrame();
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      scrollActivityToBottom();
    });
  }, [cancelActivityScrollFrame, scrollActivityToBottom]);

  const toggleOuter = () => {
    const nextOpen = userToggledOuter ? !outerOpenLocal : !outerExpanded;
    if (nextOpen) {
      autoFollowActivityRef.current = true;
    }
    setUserToggledOuter(true);
    setOuterOpenLocal(nextOpen);
  };

  useLayoutEffect(() => {
    if (!outerExpanded || !autoFollowActivityRef.current) return;
    scheduleActivityScrollToBottom();
  }, [outerExpanded, messages, isTurnStreaming, scheduleActivityScrollToBottom]);

  useEffect(() => {
    if (!outerExpanded) {
      autoFollowActivityRef.current = true;
      return;
    }
    const target = activityContentRef.current;
    if (!target || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (autoFollowActivityRef.current) {
        scheduleActivityScrollToBottom();
      }
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [outerExpanded, scheduleActivityScrollToBottom]);

  useEffect(() => cancelActivityScrollFrame, [cancelActivityScrollFrame]);

  useEffect(() => {
    if (!isTurnStreaming) return undefined;
    const interval = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(interval);
  }, [isTurnStreaming]);

  useEffect(() => {
    const wasStreaming = wasTurnStreamingRef.current;
    wasTurnStreamingRef.current = isTurnStreaming;
    if (isTurnStreaming) {
      setCompletionHoldOpen(false);
      return undefined;
    }
    if (!wasStreaming || userToggledOuter) return undefined;
    setCompletionHoldOpen(true);
    const timeout = window.setTimeout(() => setCompletionHoldOpen(false), 900);
    return () => window.clearTimeout(timeout);
  }, [isTurnStreaming, userToggledOuter]);

  const onActivityScroll = useCallback(() => {
    const el = activityScrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    autoFollowActivityRef.current = distance < ACTIVITY_SCROLL_NEAR_BOTTOM_PX;
  }, []);

  if (!hasVisibleActivity) return null;

  if (hasOnlyFileActivity) {
    return (
      <FileEditFlatActivity
        edits={fileEdits}
        active={isTurnStreaming}
        hasBodyBelow={hasBodyBelow}
        summary={summary}
        singleFilePath={singleFilePath}
        singleFileTooltipPath={singleFileTooltipPath}
        hasLiveEditingFiles={hasLiveEditingFiles}
        hasFailedFiles={hasFailedFiles}
        hasDeletedFiles={hasDeletedFiles}
        added={added}
        deleted={deleted}
        hasDiffStats={hasDiffStats}
      />
    );
  }

  return (
    <div className={cn("w-full", hasBodyBelow && "mb-2")}>
      <button
        type="button"
        onClick={toggleOuter}
        className={cn(
          "group flex max-w-full items-center gap-1.5 rounded-md px-1 py-1",
          "text-[12.5px] text-muted-foreground/72 transition-colors hover:text-muted-foreground",
        )}
        aria-expanded={outerExpanded}
        aria-label={summary}
      >
        <StreamingLabelSheen
          active={isTurnStreaming}
          className="min-w-0"
        >
          {singleFilePath ? fileActivityVerb(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles) : thoughtLabel}
        </StreamingLabelSheen>
        {singleFilePath ? (
          <FileReferenceChip
            path={singleFilePath}
            tooltipPath={singleFileTooltipPath}
            active={hasLiveEditingFiles}
            className="-my-0.5 min-w-0"
            textClassName="text-xs"
            testId="activity-header-file-reference"
          />
        ) : null}
        <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-left">
          {fileCount > 0 && hasDiffStats && (
            <span className="inline-flex min-w-0 items-center gap-1 text-muted-foreground/85">
              <DiffPair added={added} deleted={deleted} />
            </span>
          )}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform duration-200",
            outerExpanded && "rotate-90",
          )}
        />
      </button>

      {outerExpanded && (
        <div
          className={cn(
            "ml-2 mt-1 overflow-hidden border-l border-muted-foreground/14 pl-4",
          )}
        >
          <div
            ref={activityScrollRef}
            data-testid="agent-activity-scroll"
            onScroll={onActivityScroll}
            className={cn(
              CLUSTER_SCROLL_MAX_CLASS,
              "overflow-y-auto py-1 pr-1 scrollbar-thin scrollbar-track-transparent",
            )}
          >
            <div ref={activityContentRef} className="flex flex-col gap-1.5">
              {messages.map((m) => {
                if (isReasoningOnlyAssistant(m)) {
                  return (
                    <ActivityReasoningRow
                      key={m.id}
                      text={m.reasoning ?? ""}
                      streaming={isTurnStreaming && !!m.reasoningStreaming}
                    />
                  );
                }
                if (m.kind === "trace") {
                  return (
                    <ActivityTraceTimeline
                      key={m.id}
                      message={m}
                      active={isTurnStreaming}
                      cliAppsByName={cliAppsByName}
                      mcpPresetsByName={mcpPresetsByName}
                    />
                  );
                }
                return null;
              })}
              {fileEdits.length ? <FileEditGroup edits={fileEdits} /> : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function messageHasOnlyFileActivity(message: UIMessage): boolean {
  if (message.kind !== "trace" || !message.fileEdits?.length) return false;
  return traceLines(message).every((line) => !line.trim() || isFileEditTraceLine(line));
}

function FileEditFlatActivity({
  edits,
  active,
  hasBodyBelow,
  summary,
  singleFilePath,
  singleFileTooltipPath,
  hasLiveEditingFiles,
  hasFailedFiles,
  hasDeletedFiles,
  added,
  deleted,
  hasDiffStats,
}: {
  edits: FileEditSummary[];
  active: boolean;
  hasBodyBelow: boolean;
  summary: string;
  singleFilePath?: string;
  singleFileTooltipPath?: string;
  hasLiveEditingFiles: boolean;
  hasFailedFiles: boolean;
  hasDeletedFiles: boolean;
  added: number;
  deleted: number;
  hasDiffStats: boolean;
}) {
  const showRows = edits.length > 1 || edits.some((edit) => edit.status === "error" || edit.pending);
  return (
    <div className={cn("w-full", hasBodyBelow && "mb-2")} aria-label={summary}>
      <div
        className={cn(
          "flex max-w-full items-center gap-1.5 px-1 py-1",
          "text-[12.5px] text-muted-foreground/72",
        )}
      >
        <StreamingLabelSheen active={active} className="min-w-0">
          {singleFilePath
            ? fileActivityVerb(hasLiveEditingFiles, hasFailedFiles, hasDeletedFiles)
            : summary}
        </StreamingLabelSheen>
        {singleFilePath ? (
          <FileReferenceChip
            path={singleFilePath}
            tooltipPath={singleFileTooltipPath}
            active={hasLiveEditingFiles}
            className="-my-0.5 min-w-0"
            textClassName="text-xs"
            testId="activity-header-file-reference"
          />
        ) : null}
        {hasDiffStats ? (
          <span className="inline-flex min-w-0 items-center gap-1 text-muted-foreground/85">
            <DiffPair added={added} deleted={deleted} />
          </span>
        ) : null}
      </div>
      {showRows ? (
        <div className="mt-0.5 pl-4">
          <FileEditGroup edits={edits} />
        </div>
      ) : null}
    </div>
  );
}

function shortFileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function activityDurationMs(
  messages: UIMessage[],
  active: boolean,
  now: number,
  completedLatencyMs?: number,
): number {
  if (!active && Number.isFinite(completedLatencyMs) && completedLatencyMs! >= 0) {
    return Math.round(completedLatencyMs!);
  }
  const timestamps = messages
    .map((message) => message.createdAt)
    .filter((value) => Number.isFinite(value));
  if (!timestamps.length) return 0;
  const first = Math.min(...timestamps);
  const last = active && first > 1_000_000_000_000
    ? now
    : Math.max(...timestamps);
  return Math.max(0, last - first);
}

function formatActivityDuration(ms: number): string {
  const seconds = ms > 0 && ms < 1000 ? 1 : Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function traceLines(message: UIMessage): string[] {
  if (message.traces?.length) return message.traces;
  return message.content.trim() ? [message.content] : [];
}

function ActivityReasoningRow({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    if (text.length > 0) preloadMarkdownText();
  }, [text.length]);
  return (
    <div className="min-w-0 py-0.5">
      <div className="flex min-w-0 items-center gap-2 text-[13px] leading-5 text-muted-foreground/78">
        <ReasoningMarker streaming={streaming} />
        <StreamingLabelSheen active={streaming} className="min-w-0 font-medium">
          {streaming
            ? t("message.reasoningStreaming", { defaultValue: "Thinking…" })
            : t("message.reasoning", { defaultValue: "Thinking" })}
        </StreamingLabelSheen>
      </div>
      {text.trim() ? (
        <MarkdownText
          streaming={streaming}
          className={cn(
            "mt-1 min-w-0 pl-5 text-[12.5px] italic text-muted-foreground/78",
            "prose-p:my-1 prose-li:my-0.5",
            "prose-headings:mt-2 prose-headings:mb-1 prose-headings:font-medium",
            "prose-headings:text-muted-foreground/88 prose-strong:text-muted-foreground",
            "prose-h1:text-[15px] prose-h2:text-[13.5px] prose-h3:text-[12.5px] prose-h4:text-[12px]",
            "prose-a:text-muted-foreground/95 prose-a:underline hover:prose-a:opacity-90",
            "prose-code:text-[0.92em]",
          )}
        >
          {text}
        </MarkdownText>
      ) : null}
    </div>
  );
}

function ReasoningMarker({ streaming }: { streaming: boolean }) {
  const wasStreamingRef = useRef(streaming);
  const [justCompleted, setJustCompleted] = useState(false);

  useEffect(() => {
    if (wasStreamingRef.current && !streaming) {
      setJustCompleted(true);
      const timeout = window.setTimeout(() => setJustCompleted(false), 650);
      wasStreamingRef.current = streaming;
      return () => window.clearTimeout(timeout);
    }
    wasStreamingRef.current = streaming;
    return undefined;
  }, [streaming]);

  if (streaming) {
    return (
      <CircleDashed
        data-testid="activity-reasoning-marker"
        data-state="thinking"
        className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground/55"
        strokeWidth={1.8}
        aria-hidden
      />
    );
  }
  return (
    <span
      data-testid="activity-reasoning-marker"
      data-state="done"
      className={cn(
        "grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border border-emerald-500/28 text-emerald-500/78",
        "bg-emerald-500/[0.035] transition-[border-color,background-color,box-shadow,transform] duration-300 ease-out",
        justCompleted
          && "animate-in fade-in-0 zoom-in-75 shadow-[0_0_0_3px_rgba(16,185,129,0.10)] motion-reduce:animate-none",
      )}
      aria-hidden
    >
      <Check
        className={cn(
          "h-2.5 w-2.5 stroke-[2.4]",
          justCompleted && "animate-in fade-in-0 zoom-in-50 duration-300 motion-reduce:animate-none",
        )}
      />
    </span>
  );
}

function ActivityTraceList({
  lines,
  active,
}: {
  lines: string[];
  active: boolean;
}) {
  return (
    <ul className="space-y-1">
      {lines.map((line, index) => (
        <ActivityTraceRow
          key={`${line}-${index}`}
          line={line}
          active={active && index === lines.length - 1}
        />
      ))}
    </ul>
  );
}

function ActivityTraceTimeline({
  message,
  active,
  cliAppsByName,
  mcpPresetsByName,
}: {
  message: UIMessage;
  active: boolean;
  cliAppsByName: Map<string, CliAppInfo>;
  mcpPresetsByName: Map<string, McpPresetInfo>;
}) {
  const lines = traceLines(message);
  const cliRunsByLine = cliRunMapByTraceLine(message);
  const mcpRunsByLine = mcpRunMapByTraceLine(message);
  const renderedRunKeys = new Set<string>();
  const items: ReactNode[] = [];
  let normalLines: string[] = [];

  const flushNormalLines = (suffix: string) => {
    if (!normalLines.length) return;
    items.push(
      <ActivityTraceList
        key={`${message.id}:trace:${suffix}`}
        lines={normalLines}
        active={active}
      />,
    );
    normalLines = [];
  };

  lines.forEach((line, index) => {
    const cliRun = cliRunsByLine.get(line) ?? parseCliRunTrace(line);
    if (cliRun) {
      flushNormalLines(String(index));
      renderedRunKeys.add(cliRun.key);
      items.push(
        <CliRunGroup
          key={`${message.id}:cli:${cliRun.key}:${index}`}
          runs={[cliRun]}
          active={active}
          cliAppsByName={cliAppsByName}
        />,
      );
      return;
    }

    const mcpRun = mcpRunsByLine.get(line) ?? parseMcpRunTrace(line);
    if (mcpRun) {
      flushNormalLines(String(index));
      renderedRunKeys.add(mcpRun.key);
      items.push(
        <McpRunGroup
          key={`${message.id}:mcp:${mcpRun.key}:${index}`}
          runs={[mcpRun]}
          active={active}
          mcpPresetsByName={mcpPresetsByName}
        />,
      );
      return;
    }

    normalLines.push(line);
  });

  flushNormalLines("tail");

  for (const run of cliRunsByLine.values()) {
    if (renderedRunKeys.has(run.key)) continue;
    items.push(
      <CliRunGroup
        key={`${message.id}:cli:${run.key}:event`}
        runs={[run]}
        active={active}
        cliAppsByName={cliAppsByName}
      />,
    );
  }
  for (const run of mcpRunsByLine.values()) {
    if (renderedRunKeys.has(run.key)) continue;
    items.push(
      <McpRunGroup
        key={`${message.id}:mcp:${run.key}:event`}
        runs={[run]}
        active={active}
        mcpPresetsByName={mcpPresetsByName}
      />,
    );
  }

  return items.length ? <>{items}</> : null;
}

function ActivityTraceRow({ line, active }: { line: string; active: boolean }) {
  const trace = describeTraceLine(line);
  const Icon = trace.kind === "search"
    ? Search
    : trace.kind === "done"
      ? CheckCircle2
      : trace.kind === "tool"
        ? Wrench
        : Layers;
  return (
    <li className="flex min-w-0 items-start gap-2 py-0.5 text-[13px] leading-5">
      <TraceIconMark trace={trace} fallbackIcon={Icon} active={active} />
      <span className="min-w-0 flex-1">
        <span className="font-medium text-muted-foreground/85">{trace.label}</span>
        {trace.detail ? (
          <>
            <span className="text-muted-foreground/55"> </span>
            <span className="break-words text-foreground/82">{trace.detail}</span>
          </>
        ) : null}
      </span>
    </li>
  );
}

interface TraceDescription {
  kind: "search" | "tool" | "done" | "trace";
  label: string;
  detail: string;
  url?: string;
  host?: string;
}

function TraceIconMark({
  trace,
  fallbackIcon: FallbackIcon,
  active,
}: {
  trace: TraceDescription;
  fallbackIcon: LucideIcon;
  active: boolean;
}) {
  const [faviconIndex, setFaviconIndex] = useState(0);
  const faviconUrl = trace.host ? faviconUrls(trace.host)[faviconIndex] : undefined;

  useEffect(() => setFaviconIndex(0), [trace.host]);

  if (trace.url && trace.host && faviconUrl) {
    return (
      <span
        data-testid={`activity-web-favicon-${trace.host}`}
        className={cn(
          "mt-0.5 grid h-4 w-4 shrink-0 place-items-center overflow-hidden rounded-[4px] border border-border/45 bg-background shadow-[inset_0_0_0_1px_rgba(0,0,0,0.02)]",
          active && "animate-pulse",
        )}
        aria-hidden
      >
        <img
          src={faviconUrl}
          alt=""
          className="h-3.5 w-3.5 object-contain"
          onError={() => setFaviconIndex((index) => index + 1)}
        />
      </span>
    );
  }

  return (
    <FallbackIcon
      className={cn(
        "mt-0.5 h-3.5 w-3.5 shrink-0",
        trace.kind === "done"
          ? "text-emerald-500/75"
          : active
            ? "text-muted-foreground/75"
            : "text-muted-foreground/45",
      )}
      aria-hidden
    />
  );
}

function describeTraceLine(line: string): TraceDescription {
  const trimmed = line.trim();
  const functionMatch = /^([a-zA-Z0-9_.-]+)\((.*)\)$/.exec(trimmed);
  const name = functionMatch?.[1] ?? "";
  const args = functionMatch?.[2] ?? "";
  const parsedUrl = traceUrlFromArgs(args, trimmed);
  const webDetail = parsedUrl ? formatTraceUrl(parsedUrl) : "";
  const plainWebReadTrace =
    !!parsedUrl && /\b(fetch(?:ing|ed)?|read(?:ing)?|opened?|opening)\b/i.test(trimmed);
  if (/search/i.test(name)) {
    return { kind: "search", label: "Searching", detail: previewTraceDetail(args, trimmed) };
  }
  if (/fetch|read|open/i.test(name) || plainWebReadTrace) {
    return {
      kind: "tool",
      label: "Reading",
      detail: webDetail || previewTraceDetail(args, trimmed),
      url: parsedUrl?.href,
      host: parsedUrl ? displayHost(parsedUrl.hostname) : undefined,
    };
  }
  if (isShellTraceName(name)) {
    return {
      kind: "tool",
      label: "Shell",
      detail: previewShellTraceDetail(args, trimmed),
    };
  }
  if (name) {
    return { kind: "tool", label: "Using", detail: name };
  }
  if (/done|complete|success/i.test(trimmed)) {
    return { kind: "done", label: "Done", detail: trimmed };
  }
  return { kind: "trace", label: "Working", detail: trimmed };
}

function isShellTraceName(name: string): boolean {
  const compact = name.toLowerCase().split(".").pop() || name.toLowerCase();
  return new Set([
    "exec",
    "exec_command",
    "execute_command",
    "run_command",
    "run_shell",
    "shell",
    "terminal",
    "bash",
    "sh",
  ]).has(compact);
}

function previewShellTraceDetail(args: string, fallback: string): string {
  const command = shellCommandFromArgs(args) || fallback;
  return summarizeShellCommand(command);
}

function shellCommandFromArgs(args: string): string {
  const compactArgs = args.trim();
  if (!compactArgs) return "";
  try {
    const parsed = JSON.parse(compactArgs) as unknown;
    if (typeof parsed === "string") return parsed;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "";
    const record = parsed as Record<string, unknown>;
    for (const key of ["command", "cmd", "script", "input"]) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) return value;
    }
  } catch {
    return compactArgs.replace(/^["']|["']$/g, "");
  }
  return "";
}

function summarizeShellCommand(command: string): string {
  const redacted = redactShellCommand(command.replace(/\r\n/g, "\n"));
  const lines = redacted
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const firstLine = compactShellPath(lines[0] || "command");
  const firstPreview = truncateMiddle(firstLine, 92);
  if (lines.length <= 1) return firstPreview;
  return `${firstPreview} · script, ${lines.length} lines`;
}

function redactShellCommand(command: string): string {
  return command
    .replace(/\b((?:[A-Z0-9_]*)(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASS|AUTH)(?:[A-Z0-9_]*))=(?:"[^"]*"|'[^']*'|[^\s]+)/gi, "$1=••••")
    .replace(/\b(Bearer)\s+[A-Za-z0-9._~+/=-]+/gi, "$1 ••••")
    .replace(/(--(?:api-?key|token|secret|password)(?:=|\s+))(?:"[^"]*"|'[^']*'|[^\s]+)/gi, "$1••••")
    .replace(/([?&](?:api_?key|token|secret|password)=)[^&\s]+/gi, "$1••••");
}

function compactShellPath(value: string): string {
  return value
    .replace(/\/Users\/[^/\s"']+/g, "~")
    .replace(/\/private\/tmp\/[^\s"']+/g, "/tmp/…")
    .replace(/\/var\/folders\/[^\s"']+/g, "/var/folders/…");
}

function truncateMiddle(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const head = Math.ceil((maxLength - 1) * 0.62);
  const tail = Math.floor((maxLength - 1) * 0.38);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function traceUrlFromArgs(args: string, fallback: string): URL | null {
  const candidates: string[] = [];
  const compactArgs = args.trim();
  if (compactArgs) {
    try {
      collectUrlCandidates(JSON.parse(compactArgs), candidates);
    } catch {
      candidates.push(compactArgs.replace(/^["']|["']$/g, ""));
    }
  }
  candidates.push(fallback);
  for (const candidate of candidates) {
    const url = parsePublicHttpUrl(candidate);
    if (url) return url;
    const embedded = candidate.match(/https?:\/\/[^\s"'<>),]+/i)?.[0];
    if (embedded) {
      const embeddedUrl = parsePublicHttpUrl(embedded);
      if (embeddedUrl) return embeddedUrl;
    }
  }
  return null;
}

function collectUrlCandidates(value: unknown, candidates: string[]) {
  if (typeof value === "string") {
    candidates.push(value);
    return;
  }
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 6)) collectUrlCandidates(item, candidates);
    return;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["url", "uri", "href", "link"]) {
    if (typeof record[key] === "string") candidates.push(record[key]);
  }
}

function parsePublicHttpUrl(value: string): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (isPrivateHostname(url.hostname)) return null;
    return url;
  } catch {
    return null;
  }
}

function isPrivateHostname(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (!host || host === "localhost" || host.endsWith(".local")) return true;
  if (!host.includes(".") && !host.includes(":")) return true;
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (ipv4) {
    const [, aText, bText] = ipv4;
    const a = Number(aText);
    const b = Number(bText);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168)
    );
  }
  return host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80:");
}

function displayHost(hostname: string): string {
  return hostname.replace(/^www\./i, "").toLowerCase();
}

function formatTraceUrl(url: URL): string {
  const host = displayHost(url.hostname);
  const path = url.pathname && url.pathname !== "/" ? url.pathname : "";
  return `${host}${path}`;
}

function previewTraceDetail(args: string, fallback: string): string {
  const compactArgs = args.trim();
  if (!compactArgs) return fallback;
  try {
    const parsed = JSON.parse(compactArgs) as unknown;
    const preview = previewMcpArgs(parsed);
    if (preview) return preview;
  } catch {
    // Keep the original trace text for non-JSON progress hints.
  }
  return compactArgs.replace(/^["']|["']$/g, "");
}

const CLI_RUN_TOOL_NAMES = new Set(["run_cli_app", "cli_anything_run"]);
const CLI_RUN_STATUS_RANK: Record<CliRunStatus, number> = { running: 1, done: 2, error: 3 };
const MCP_RUN_STATUS_RANK: Record<McpRunStatus, number> = { running: 1, done: 2, error: 3 };
const MCP_TOOL_NAME_RE = /^mcp_([a-z0-9_-]+?)_(.+)$/i;

function isCliRunTraceLine(line: string): boolean {
  return /^(run_cli_app|cli_anything_run)\(/.test(line.trim());
}

function isMcpRunTraceLine(line: string): boolean {
  return MCP_TOOL_NAME_RE.test(line.trim().split("(", 1)[0] ?? "");
}

function isFileEditTraceLine(line: string): boolean {
  return /^(write_file|edit_file|apply_patch)\(/.test(line.trim());
}

function parseCliRunTrace(line: string, status: CliRunStatus = "running"): CliRunSummary | null {
  const match = /^(run_cli_app|cli_anything_run)\((.*)\)$/.exec(line.trim());
  if (!match) return null;
  const argsText = match[2].trim();
  let argsObject: unknown = {};
  if (argsText) {
    try {
      argsObject = JSON.parse(argsText);
    } catch {
      return {
        key: line,
        name: "cli",
        args: [argsText],
        json: false,
        status,
      };
    }
  }
  return cliRunFromArguments(argsObject, { key: line, status });
}

function parseToolEventArguments(event: ToolProgressEvent): unknown {
  const fnArgs = (event as { function?: { arguments?: unknown } }).function?.arguments;
  const raw = fnArgs ?? event.arguments;
  if (typeof raw !== "string") return raw ?? {};
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { args: [raw] };
  }
}

function cliRunStatusFromPhase(phase: unknown): CliRunStatus {
  if (phase === "error") return "error";
  if (phase === "end") return "done";
  return "running";
}

function cliRunError(event: ToolProgressEvent): string | undefined {
  const error = event.error;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") return JSON.stringify(error);
  return undefined;
}

function toolEventName(event: ToolProgressEvent): string {
  return typeof (event as { function?: { name?: unknown } }).function?.name === "string"
    ? String((event as { function?: { name?: unknown } }).function?.name)
    : typeof event.name === "string"
      ? event.name
      : "";
}

function cliRunFromArguments(
  argsObject: unknown,
  options: { key: string; status: CliRunStatus; error?: string },
): CliRunSummary {
  if (!argsObject || typeof argsObject !== "object" || Array.isArray(argsObject)) {
    return {
      key: options.key,
      name: "cli",
      args: [],
      json: false,
      status: options.status,
      error: options.error,
    };
  }
  const record = argsObject as Record<string, unknown>;
  const appName = typeof record.name === "string" && record.name.trim()
    ? record.name.trim()
    : "cli";
  const rawArgs = Array.isArray(record.args) ? record.args : [];
  const cliArgs = rawArgs.filter((item): item is string => typeof item === "string");
  return {
    key: options.key,
    name: appName,
    args: cliArgs,
    json: record.json === true || record.json === "true",
    workingDir: typeof record.working_dir === "string" ? record.working_dir : undefined,
    status: options.status,
    error: options.error,
  };
}

function cliRunFromEvent(event: ToolProgressEvent): CliRunSummary | null {
  const name = toolEventName(event);
  if (!CLI_RUN_TOOL_NAMES.has(name)) return null;
  const argsObject = parseToolEventArguments(event);
  const key = event.call_id ? `call:${event.call_id}` : `${name}:${JSON.stringify(argsObject)}`;
  return cliRunFromArguments(argsObject, {
    key,
    status: cliRunStatusFromPhase(event.phase),
    error: cliRunError(event),
  });
}

function cliRunMapByTraceLine(message: UIMessage): Map<string, CliRunSummary> {
  const runsByLine = new Map<string, CliRunSummary>();
  for (const event of message.toolEvents ?? []) {
    const run = cliRunFromEvent(event);
    if (!run) continue;
    const line = formatToolCallTrace(event);
    if (!line) continue;
    runsByLine.set(line, mergeCliRun(runsByLine.get(line), run));
  }
  return runsByLine;
}

function mergeCliRun(existing: CliRunSummary | undefined, incoming: CliRunSummary): CliRunSummary {
  if (!existing) return incoming;
  return CLI_RUN_STATUS_RANK[incoming.status] >= CLI_RUN_STATUS_RANK[existing.status]
    ? { ...existing, ...incoming }
    : existing;
}

function collectCliRuns(messages: UIMessage[]): CliRunSummary[] {
  const runsByKey = new Map<string, CliRunSummary>();
  for (const message of messages) {
    if (message.kind !== "trace") continue;
    let hasStructuredCliRun = false;
    for (const event of message.toolEvents ?? []) {
      const run = cliRunFromEvent(event);
      if (!run) continue;
      hasStructuredCliRun = true;
      runsByKey.set(run.key, mergeCliRun(runsByKey.get(run.key), run));
    }
    if (hasStructuredCliRun) continue;
    for (const line of traceLines(message)) {
      const run = parseCliRunTrace(line);
      if (!run || runsByKey.has(run.key)) continue;
      runsByKey.set(run.key, run);
    }
  }
  return [...runsByKey.values()];
}

function titleFromPresetName(name: string): string {
  return name
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || name;
}

function previewScalar(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function previewMcpArgs(argsObject: unknown): string {
  if (!argsObject || typeof argsObject !== "object" || Array.isArray(argsObject)) {
    return previewScalar(argsObject) ?? "";
  }
  const record = argsObject as Record<string, unknown>;
  for (const key of ["url", "query", "q", "path", "name", "id", "title", "message", "text"]) {
    const preview = previewScalar(record[key]);
    if (preview) return `${key}: ${preview}`;
  }
  const entries = Object.entries(record)
    .filter(([, value]) => previewScalar(value) !== null)
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${previewScalar(value)}`);
  return entries.join(" · ");
}

function mcpRunFromToolName(
  toolName: string,
  argsObject: unknown,
  options: { key: string; status: McpRunStatus; error?: string },
): McpRunSummary | null {
  const match = MCP_TOOL_NAME_RE.exec(toolName);
  if (!match) return null;
  const presetName = match[1].toLowerCase();
  return {
    key: options.key,
    presetName,
    displayName: titleFromPresetName(presetName),
    toolName: match[2],
    argsPreview: previewMcpArgs(argsObject),
    status: options.status,
    error: options.error,
  };
}

function parseMcpRunTrace(line: string, status: McpRunStatus = "running"): McpRunSummary | null {
  const match = /^([a-z0-9_-]+)\((.*)\)$/i.exec(line.trim());
  if (!match || !MCP_TOOL_NAME_RE.test(match[1])) return null;
  const argsText = match[2].trim();
  let argsObject: unknown = {};
  if (argsText) {
    try {
      argsObject = JSON.parse(argsText);
    } catch {
      argsObject = argsText;
    }
  }
  return mcpRunFromToolName(match[1], argsObject, { key: line, status });
}

function mcpRunFromEvent(event: ToolProgressEvent): McpRunSummary | null {
  const name = toolEventName(event);
  if (!MCP_TOOL_NAME_RE.test(name)) return null;
  const argsObject = parseToolEventArguments(event);
  const key = event.call_id ? `call:${event.call_id}` : `${name}:${JSON.stringify(argsObject)}`;
  return mcpRunFromToolName(name, argsObject, {
    key,
    status: cliRunStatusFromPhase(event.phase),
    error: cliRunError(event),
  });
}

function mcpRunMapByTraceLine(message: UIMessage): Map<string, McpRunSummary> {
  const runsByLine = new Map<string, McpRunSummary>();
  for (const event of message.toolEvents ?? []) {
    const run = mcpRunFromEvent(event);
    if (!run) continue;
    const line = formatToolCallTrace(event);
    if (!line) continue;
    runsByLine.set(line, mergeMcpRun(runsByLine.get(line), run));
  }
  return runsByLine;
}

function mergeMcpRun(existing: McpRunSummary | undefined, incoming: McpRunSummary): McpRunSummary {
  if (!existing) return incoming;
  return MCP_RUN_STATUS_RANK[incoming.status] >= MCP_RUN_STATUS_RANK[existing.status]
    ? { ...existing, ...incoming }
    : existing;
}

function collectMcpRuns(messages: UIMessage[]): McpRunSummary[] {
  const runsByKey = new Map<string, McpRunSummary>();
  for (const message of messages) {
    if (message.kind !== "trace") continue;
    let hasStructuredMcpRun = false;
    for (const event of message.toolEvents ?? []) {
      const run = mcpRunFromEvent(event);
      if (!run) continue;
      hasStructuredMcpRun = true;
      runsByKey.set(run.key, mergeMcpRun(runsByKey.get(run.key), run));
    }
    if (hasStructuredMcpRun) continue;
    for (const line of traceLines(message)) {
      const run = parseMcpRunTrace(line);
      if (!run || runsByKey.has(run.key)) continue;
      runsByKey.set(run.key, run);
    }
  }
  return [...runsByKey.values()];
}

function displayCliArg(arg: string): string {
  return /\s/.test(arg) ? JSON.stringify(arg) : arg;
}

function formatCliArgs(run: CliRunSummary): string {
  const args = [...(run.json ? ["--json"] : []), ...run.args].map(displayCliArg);
  return args.join(" ");
}

function cliActivitySummaryKey(status: CliRunStatus | undefined, active: boolean): string {
  if (status === "error") return "message.cliActivityFailedOne";
  return active && status === "running" ? "message.cliActivityRunningOne" : "message.cliActivityRanOne";
}

function cliActivitySummaryDefault(status: CliRunStatus | undefined, active: boolean): string {
  if (status === "error") return "Failed @{{name}}";
  return `${active && status === "running" ? "Using" : "Used"} @{{name}}`;
}

function cliActivityManySummaryKey(runs: CliRunSummary[], active: boolean): string {
  if (runs.some((run) => run.status === "error")) return "message.cliActivityFailedMany";
  return active && runs.some((run) => run.status === "running")
    ? "message.cliActivityRunningMany"
    : "message.cliActivityRanMany";
}

function cliActivityManySummaryDefault(runs: CliRunSummary[], active: boolean): string {
  if (runs.some((run) => run.status === "error")) return "{{count}} CLI apps failed";
  return `${active && runs.some((run) => run.status === "running") ? "Using" : "Used"} {{count}} CLI apps`;
}

function cliRunLabelKey(run: CliRunSummary, active: boolean): string {
  if (run.status === "error") return "message.cliRunFailed";
  return active && run.status === "running" ? "message.cliRunRunning" : "message.cliRunRan";
}

function cliRunLabelDefault(run: CliRunSummary, active: boolean): string {
  if (run.status === "error") return "Failed";
  return active && run.status === "running" ? "Using" : "Used";
}

function mcpActivitySummaryKey(status: McpRunStatus | undefined, active: boolean): string {
  if (status === "error") return "message.mcpActivityFailedOne";
  return active && status === "running" ? "message.mcpActivityRunningOne" : "message.mcpActivityRanOne";
}

function mcpActivitySummaryDefault(status: McpRunStatus | undefined, active: boolean): string {
  if (status === "error") return "Failed {{name}}";
  return `${active && status === "running" ? "Using" : "Used"} {{name}}`;
}

function mcpActivityManySummaryKey(runs: McpRunSummary[], active: boolean): string {
  if (runs.some((run) => run.status === "error")) return "message.mcpActivityFailedMany";
  return active && runs.some((run) => run.status === "running")
    ? "message.mcpActivityRunningMany"
    : "message.mcpActivityRanMany";
}

function mcpActivityManySummaryDefault(runs: McpRunSummary[], active: boolean): string {
  if (runs.some((run) => run.status === "error")) return "{{count}} MCP calls failed";
  return `${active && runs.some((run) => run.status === "running") ? "Using" : "Used"} {{count}} MCP tools`;
}

function mcpRunLabelKey(run: McpRunSummary, active: boolean): string {
  if (run.status === "error") return "message.mcpRunFailed";
  return active && run.status === "running" ? "message.mcpRunRunning" : "message.mcpRunRan";
}

function mcpRunLabelDefault(run: McpRunSummary, active: boolean): string {
  if (run.status === "error") return "Failed";
  return active && run.status === "running" ? "Using" : "Used";
}

function fileActivityVerb(editing: boolean, failed: boolean, deleted: boolean): string {
  if (failed) return "Failed";
  if (deleted) return editing ? "Deleting" : "Deleted";
  return editing ? "Editing" : "Edited";
}

function fileActivitySummaryKey(editing: boolean, failed: boolean, deleted: boolean): string {
  if (failed) return "message.fileActivityFailedOne";
  if (deleted) return editing ? "message.fileActivityDeletingOne" : "message.fileActivityDeletedOne";
  return editing ? "message.fileActivityEditingOne" : "message.fileActivityEditedOne";
}

function fileActivityManySummaryKey(editing: boolean, failed: boolean, deleted: boolean): string {
  if (failed) return "message.fileActivityFailedMany";
  if (deleted) return editing ? "message.fileActivityDeletingMany" : "message.fileActivityDeletedMany";
  return editing ? "message.fileActivityEditingMany" : "message.fileActivityEditedMany";
}

function fileEditCallKey(edit: UIFileEdit): string {
  if (edit.call_id) return `${edit.call_id}|${edit.tool}`;
  return `${edit.tool}|${edit.path}`;
}

function collectFileEdits(messages: UIMessage[]): UIFileEdit[] {
  const edits: UIFileEdit[] = [];
  for (const message of messages) {
    if (message.kind === "trace" && message.fileEdits?.length) {
      edits.push(...message.fileEdits);
    }
  }
  return edits;
}

function latestFileEditEvents(edits: UIFileEdit[]): UIFileEdit[] {
  const order: string[] = [];
  const byKey = new Map<string, UIFileEdit>();
  for (const edit of edits) {
    const key = fileEditCallKey(edit);
    if (!byKey.has(key)) order.push(key);
    byKey.set(key, edit);
  }
  return order.map((key) => byKey.get(key)).filter(Boolean) as UIFileEdit[];
}

function summarizeFileEdits(edits: UIFileEdit[], active: boolean): FileEditSummary[] {
  interface MutableSummary {
    key: string;
    path: string;
    absolute_path?: string;
    added: number;
    deleted: number;
    approximate: boolean;
    binary: boolean;
    pending: boolean;
    hasSuccessfulChange: boolean;
    hasActiveEditing: boolean;
    hasFailed: boolean;
    operation?: UIFileEdit["operation"];
    error?: string;
  }

  const order: string[] = [];
  const byPath = new Map<string, MutableSummary>();
  for (const edit of latestFileEditEvents(edits)) {
    const key = edit.path || edit.call_id || edit.tool;
    let summary = byPath.get(key);
    if (!summary) {
      summary = {
        key,
        path: edit.path || "",
        absolute_path: edit.absolute_path,
        added: 0,
        deleted: 0,
        approximate: false,
        binary: false,
        pending: false,
        hasSuccessfulChange: false,
        hasActiveEditing: false,
        hasFailed: false,
        operation: undefined,
      };
      byPath.set(key, summary);
      order.push(key);
    }

    if (edit.path && !summary.path) {
      summary.path = edit.path;
    }
    if (edit.absolute_path) {
      summary.absolute_path = edit.absolute_path;
    }
    if (edit.operation === "delete") {
      summary.operation = "delete";
    }
    summary.pending = summary.pending || !!edit.pending || !edit.path;
    if (!edit.path && edit.pending) {
      if (active && edit.status === "editing") {
        summary.hasActiveEditing = true;
        summary.approximate = summary.approximate || !!edit.approximate;
        if (!edit.binary) {
          summary.added += edit.added;
          summary.deleted += edit.deleted;
        }
      }
      continue;
    }
    if (active && edit.status === "editing") {
      summary.hasActiveEditing = true;
      summary.binary = summary.binary || !!edit.binary;
      summary.approximate = summary.approximate || !!edit.approximate;
      if (!edit.binary) {
        summary.added += edit.added;
        summary.deleted += edit.deleted;
      }
      continue;
    }

    if (edit.status === "error") {
      summary.hasFailed = true;
      summary.error = edit.error ?? summary.error;
      continue;
    }

    summary.hasSuccessfulChange = true;
    summary.binary = summary.binary || !!edit.binary;
    summary.approximate = active && (summary.approximate || !!edit.approximate);
    if (!edit.binary) {
      summary.added += edit.added;
      summary.deleted += edit.deleted;
    }
  }

  return order.flatMap((key) => {
    const summary = byPath.get(key)!;
    if (
      !summary.path
      && !summary.hasActiveEditing
      && !summary.hasSuccessfulChange
      && !summary.hasFailed
    ) {
      return [];
    }
    const status: UIFileEdit["status"] = summary.hasActiveEditing
      ? "editing"
      : summary.hasSuccessfulChange
        ? "done"
        : summary.hasFailed
          ? "error"
          : "done";
    return [{
      key: summary.key,
      path: summary.path,
      absolute_path: summary.absolute_path,
      added: summary.added,
      deleted: summary.deleted,
      approximate: summary.approximate,
      binary: summary.binary,
      status,
      operation: summary.operation,
      pending: summary.pending && !summary.path,
      error: summary.error,
    }];
  });
}

function hasVisibleDiffStats(edit: Pick<FileEditSummary, "added" | "deleted">): boolean {
  return edit.added > 0 || edit.deleted > 0;
}

function formatFileEditError(error?: string): string {
  const firstLine = (error || "").replace(/\s+/g, " ").trim();
  if (!firstLine) return "";
  const cleaned = firstLine
    .replace(/^Error applying patch:\s*/i, "")
    .replace(/^Error writing file:\s*/i, "")
    .replace(/^Error editing file:\s*/i, "")
    .replace(/^Error:\s*/i, "");

  return cleaned
    .replace(/^old_text not found in (.+)$/i, "Target text was not found in $1.")
    .replace(/^old_text appears multiple times in (.+)$/i, "Target text matched multiple places in $1.")
    .replace(/^file to (?:update|delete) does not exist: (.+)$/i, "File does not exist: $1.")
    .replace(/^path to (?:update|delete) is not a file: (.+)$/i, "Path is not a file: $1.")
    .slice(0, 180);
}

function CliRunGroup({
  runs,
  active,
  cliAppsByName,
}: {
  runs: CliRunSummary[];
  active: boolean;
  cliAppsByName: Map<string, CliAppInfo>;
}) {
  if (runs.length === 0) return null;
  return (
    <ul className="space-y-1" data-testid="activity-cli-runs">
      {runs.map((run) => (
        <CliRunRow
          key={run.key}
          run={run}
          active={active}
          app={cliAppsByName.get(run.name.toLowerCase())}
        />
      ))}
    </ul>
  );
}

function CliRunRow({ run, active, app }: { run: CliRunSummary; active: boolean; app?: CliAppInfo }) {
  const { t } = useTranslation();
  const [logoIndex, setLogoIndex] = useState(0);
  const args = formatCliArgs(run);
  const failed = run.status === "error";
  const rowActive = active && run.status === "running";
  const color = failed ? "#DC2626" : app?.brand_color || "#0891B2";
  const logoUrls = useMemo(() => logoFallbackUrls(app?.logo_url), [app?.logo_url]);
  const logoUrl = logoUrls[logoIndex];
  const label = t(cliRunLabelKey(run, active), {
    defaultValue: cliRunLabelDefault(run, active),
  });

  useEffect(() => setLogoIndex(0), [app?.logo_url]);

  return (
    <li
      className="flex min-w-0 items-center gap-2 py-0.5 text-[13px] leading-5"
      title={`${label} @${run.name}${args ? ` ${args}` : ""}${run.error ? ` ${run.error}` : ""}`}
    >
      <span
        data-testid={`activity-cli-logo-${run.name.toLowerCase()}`}
        className={cn(
          "grid h-4 w-4 shrink-0 place-items-center overflow-hidden rounded-[4px] border text-[6.5px] font-semibold text-white",
          rowActive && "animate-pulse",
        )}
        style={{
          borderColor: alphaColor(color, 22),
          backgroundColor: logoUrl ? "hsl(var(--background))" : color,
          boxShadow: rowActive ? `0 0 0 3px ${alphaColor(color, 9)}` : undefined,
        }}
        aria-hidden
      >
        {logoUrl ? (
          <img
            src={logoUrl}
            alt=""
            className="h-[78%] w-[78%] object-contain"
            onError={() => setLogoIndex((index) => index + 1)}
          />
        ) : app ? (
          cliAppInitials(app).slice(0, 2)
        ) : (
          <Terminal className="h-3 w-3" aria-hidden />
        )}
      </span>
      <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
        <StreamingLabelSheen active={rowActive} className="shrink-0 font-medium text-muted-foreground/85">
          {label}
        </StreamingLabelSheen>
        <span className="max-w-[11rem] shrink-0 truncate font-mono text-[12.5px] font-semibold text-foreground/90">
          @{run.name}
        </span>
        {failed ? (
          <AlertCircle className="h-3 w-3 shrink-0 translate-y-[0.16em] text-destructive/75" aria-hidden />
        ) : null}
        {args ? (
          <>
            <span className="shrink-0 text-muted-foreground/36">·</span>
            <span className="min-w-0 truncate font-mono text-[12px] text-muted-foreground/72">
              {args}
            </span>
          </>
        ) : null}
        {run.error ? (
          <>
            <span className="shrink-0 text-muted-foreground/30">·</span>
            <span className="min-w-0 truncate text-[12px] text-destructive/72">
              {run.error}
            </span>
          </>
        ) : null}
        {run.workingDir && !run.error ? (
          <>
            <span className="shrink-0 text-muted-foreground/30">·</span>
            <span className="min-w-0 truncate text-[12px] text-muted-foreground/55">
              {run.workingDir}
            </span>
          </>
        ) : null}
      </span>
    </li>
  );
}

function McpRunGroup({
  runs,
  active,
  mcpPresetsByName,
}: {
  runs: McpRunSummary[];
  active: boolean;
  mcpPresetsByName: Map<string, McpPresetInfo>;
}) {
  if (runs.length === 0) return null;
  return (
    <ul className="space-y-1" data-testid="activity-mcp-runs">
      {runs.map((run) => (
        <McpRunRow
          key={run.key}
          run={run}
          active={active}
          preset={mcpPresetsByName.get(run.presetName.toLowerCase())}
        />
      ))}
    </ul>
  );
}

function McpRunRow({ run, active, preset }: { run: McpRunSummary; active: boolean; preset?: McpPresetInfo }) {
  const { t } = useTranslation();
  const [logoIndex, setLogoIndex] = useState(0);
  const failed = run.status === "error";
  const rowActive = active && run.status === "running";
  const color = failed ? "#DC2626" : preset?.brand_color || "#6D5DF6";
  const logoUrls = useMemo(() => logoFallbackUrls(preset?.logo_url), [preset?.logo_url]);
  const logoUrl = logoUrls[logoIndex];
  const displayName = preset?.display_name || run.displayName;
  const label = t(mcpRunLabelKey(run, active), {
    defaultValue: mcpRunLabelDefault(run, active),
  });

  useEffect(() => setLogoIndex(0), [preset?.logo_url]);

  return (
    <li
      className="flex min-w-0 items-center gap-2 py-0.5 text-[13px] leading-5"
      title={`${label} ${displayName} ${run.toolName}${run.argsPreview ? ` ${run.argsPreview}` : ""}${run.error ? ` ${run.error}` : ""}`}
    >
      <span
        data-testid={`activity-mcp-logo-${run.presetName.toLowerCase()}`}
        className={cn(
          "grid h-4 w-4 shrink-0 place-items-center overflow-hidden rounded-[4px] border text-[6.5px] font-semibold text-white",
          rowActive && "animate-pulse",
        )}
        style={{
          borderColor: alphaColor(color, 22),
          backgroundColor: logoUrl ? "hsl(var(--background))" : color,
          boxShadow: rowActive ? `0 0 0 3px ${alphaColor(color, 9)}` : undefined,
        }}
        aria-hidden
      >
        {logoUrl ? (
          <img
            src={logoUrl}
            alt=""
            className="h-[78%] w-[78%] object-contain"
            onError={() => setLogoIndex((index) => index + 1)}
          />
        ) : preset ? (
          mcpPresetInitials(preset).slice(0, 2)
        ) : (
          <Server className="h-3 w-3" aria-hidden />
        )}
      </span>
      <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
        <StreamingLabelSheen active={rowActive} className="shrink-0 font-medium text-muted-foreground/85">
          {label}
        </StreamingLabelSheen>
        <span className="max-w-[12rem] shrink-0 truncate text-[12.5px] font-semibold text-foreground/90">
          {displayName}
        </span>
        {failed ? (
          <AlertCircle className="h-3 w-3 shrink-0 translate-y-[0.16em] text-destructive/75" aria-hidden />
        ) : null}
        <span className="shrink-0 text-muted-foreground/36">·</span>
        <span className="min-w-0 truncate font-mono text-[12px] text-muted-foreground/72">
          {run.toolName}
          {run.argsPreview ? ` · ${run.argsPreview}` : ""}
        </span>
        {run.error ? (
          <>
            <span className="shrink-0 text-muted-foreground/30">·</span>
            <span className="min-w-0 truncate text-[12px] text-destructive/72">
              {run.error}
            </span>
          </>
        ) : null}
      </span>
    </li>
  );
}

function alphaColor(color: string, percent: number): string {
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const alpha = Math.round((percent / 100) * 255)
      .toString(16)
      .padStart(2, "0");
    return `${color}${alpha}`;
  }
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

function FileEditGroup({ edits }: { edits: FileEditSummary[] }) {
  if (edits.length === 0) return null;
  return (
    <ul className="space-y-1">
      {edits.map((edit) => (
        <FileEditRow key={edit.key} edit={edit} />
      ))}
    </ul>
  );
}

function FileEditRow({ edit }: { edit: FileEditSummary }) {
  const { t } = useTranslation();
  const editing = edit.status === "editing";
  const failed = edit.status === "error";
  const hasCountedDiff = !failed && !edit.binary && hasVisibleDiffStats(edit);
  const failureDetail = failed
    ? formatFileEditError(edit.error)
      || t("message.fileEditFailedFallback", { defaultValue: "File change was not applied." })
    : "";
  return (
    <li
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-0.5 text-xs"
      title={failureDetail || edit.absolute_path || edit.path}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="grid h-5 w-5 shrink-0 place-items-center text-muted-foreground/50">
          {failed ? (
            <AlertCircle className="h-3.5 w-3.5 text-destructive/75" aria-hidden />
          ) : editing ? (
            <CircleDashed className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500/75" aria-hidden />
          )}
        </span>
        {edit.pending && !edit.path ? (
          <StreamingLabelSheen
            active={editing}
            className="min-w-0 text-[12px] font-medium text-muted-foreground"
          >
            {t("message.fileEditPreparing", { defaultValue: "Preparing file edit…" })}
          </StreamingLabelSheen>
        ) : (
          <FileReferenceChip
            path={edit.path}
            tooltipPath={edit.absolute_path}
            display="path"
            active={editing}
            className="min-w-0"
            textClassName="text-[12px]"
            testId="activity-file-reference"
          />
        )}
        {failed ? (
          <span className="min-w-0 truncate text-[11px] leading-4 text-destructive/75">
            {failureDetail}
          </span>
        ) : null}
      </div>
      {hasCountedDiff ? (
        <DiffPair added={edit.added} deleted={edit.deleted} />
      ) : null}
    </li>
  );
}

function DiffPair({ added, deleted }: { added: number; deleted: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-baseline gap-1.5 leading-[inherit] tabular-nums"
      data-testid="activity-diff-pair"
    >
      <DiffValue
        sign="+"
        value={added}
        className="text-emerald-600/75 dark:text-emerald-300/75"
      />
      <DiffValue
        sign="-"
        value={deleted}
        className="text-rose-600/70 dark:text-rose-300/75"
      />
    </span>
  );
}

function DiffValue({ sign, value, className }: { sign: string; value: number; className: string }) {
  const safeValue = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  return (
    <span
      className={cn("inline-flex items-baseline leading-[inherit]", className)}
      aria-label={`${sign}${safeValue}`}
    >
      <span className="inline-flex items-baseline leading-none" aria-hidden>
        {sign}
        <AnimatedNumber value={safeValue} />
      </span>
      <span className="sr-only">{sign}{safeValue}</span>
    </span>
  );
}

function AnimatedNumber({ value }: { value: number }) {
  const safeValue = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  const [display, setDisplay] = useState(0);
  const displayRef = useRef(0);

  const setAnimatedDisplay = useCallback((next: number) => {
    displayRef.current = next;
    setDisplay(next);
  }, []);

  useEffect(() => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      setAnimatedDisplay(safeValue);
      return;
    }
    const start = displayRef.current;
    const delta = safeValue - start;
    if (delta === 0) {
      setAnimatedDisplay(safeValue);
      return;
    }
    const duration = 260;
    const startedAt = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedDisplay(Math.round(start + delta * eased));
      if (progress < 1) {
        frame = window.requestAnimationFrame(tick);
        return;
      }
      displayRef.current = safeValue;
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [safeValue, setAnimatedDisplay]);

  return <RollingNumber value={display} />;
}

function RollingNumber({ value }: { value: number }) {
  const digits = String(value).split("");
  return (
    <span className="inline-flex items-baseline leading-none" aria-hidden>
      {digits.map((digit, index) => (
        <RollingDigit
          key={`${digits.length}-${index}`}
          digit={Number(digit)}
        />
      ))}
    </span>
  );
}

function RollingDigit({ digit }: { digit: number }) {
  const safeDigit = Number.isFinite(digit) ? Math.min(9, Math.max(0, digit)) : 0;
  return (
    <span className="relative inline-block h-[1em] w-[0.62em] overflow-hidden align-baseline leading-none">
      <span className="invisible block h-[1em] leading-none">0</span>
      <span
        className="absolute inset-x-0 top-0 flex flex-col transition-transform duration-200 ease-out will-change-transform"
        style={{ transform: `translateY(-${safeDigit}em)` }}
      >
        {Array.from({ length: 10 }, (_, n) => (
          <span key={n} className="block h-[1em] leading-none">
            {n}
          </span>
        ))}
      </span>
    </span>
  );
}
