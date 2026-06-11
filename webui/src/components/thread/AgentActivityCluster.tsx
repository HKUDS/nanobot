import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  FileImage,
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
import { StreamingLabelSheen } from "@/components/MessageBubble";
import { ActivityEvidencePreview } from "@/components/thread/activity/ActivityEvidencePreview";
import { ActivityGroup } from "@/components/thread/activity/ActivityGroup";
import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { DiffPair } from "@/components/thread/activity/DiffPair";
import { FileEditGroup, hasVisibleDiffStats, type FileEditSummary } from "@/components/thread/activity/FileEditRow";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import {
  activityEvidenceFromMessageMedia,
  activityEvidenceFromToolEvent,
  isAgentActivityMember,
  isReasoningOnlyAssistant,
  type ActivityEvidence,
} from "@/lib/activity-timeline";
import { faviconUrls, logoFallbackUrls } from "@/lib/provider-brand";
import { formatToolCallTrace } from "@/lib/tool-traces";
import { cn } from "@/lib/utils";
import type { CliAppInfo, McpPresetInfo, ToolProgressEvent, UIFileEdit, UIMessage } from "@/lib/types";

/** Scrollport height for the Cursor-style “live trace” strip (tailwind spacing). */
const CLUSTER_SCROLL_MAX_CLASS = "max-h-52";
const ACTIVITY_SCROLL_NEAR_BOTTOM_PX = 24;

export { isAgentActivityMember, isReasoningOnlyAssistant };

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
  onOpenFilePreview?: (path: string) => void;
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
  onOpenFilePreview,
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
        onOpenFilePreview={onOpenFilePreview}
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
            previewPath={singleFileTooltipPath || singleFilePath}
            onOpen={onOpenFilePreview}
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
            "ml-1 mt-1 overflow-hidden pl-1",
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
            <div ref={activityContentRef} className="flex flex-col gap-0.5">
              {messages.map((m) => {
                if (isReasoningOnlyAssistant(m)) {
                  return (
                    <ReasoningRow
                      key={m.id}
                      text={m.reasoning ?? ""}
                      streaming={isTurnStreaming && !!m.reasoningStreaming}
                      onOpenFilePreview={onOpenFilePreview}
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
              {fileEdits.length ? (
                <FileEditGroup
                  edits={fileEdits}
                  onOpenFilePreview={onOpenFilePreview}
                />
              ) : null}
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
  onOpenFilePreview,
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
  onOpenFilePreview?: (path: string) => void;
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
            previewPath={singleFileTooltipPath || singleFilePath}
            onOpen={onOpenFilePreview}
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
          <FileEditGroup edits={edits} onOpenFilePreview={onOpenFilePreview} />
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

function ActivityTraceList({
  lines,
  active,
  evidenceByLine,
}: {
  lines: string[];
  active: boolean;
  evidenceByLine?: Map<string, ActivityEvidence[]>;
}) {
  return (
    <ul className="space-y-1">
      {lines.map((line, index) => (
        <ActivityTraceRow
          key={`${line}-${index}`}
          line={line}
          active={active && index === lines.length - 1}
          evidence={evidenceByLine?.get(line) ?? []}
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
  const evidenceByLine = toolEvidenceByTraceLine(message);
  const trailingEvidence = activityEvidenceFromMessageMedia(message);
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
        evidenceByLine={evidenceByLine}
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
      const evidence = evidenceByLine.get(line) ?? [];
      if (evidence.length) {
        items.push(
          <ActivityEvidenceList
            key={`${message.id}:cli-evidence:${cliRun.key}:${index}`}
            evidence={evidence}
          />,
        );
      }
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
      const evidence = evidenceByLine.get(line) ?? [];
      if (evidence.length) {
        items.push(
          <ActivityEvidenceList
            key={`${message.id}:mcp-evidence:${mcpRun.key}:${index}`}
            evidence={evidence}
          />,
        );
      }
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

  if (trailingEvidence.length) {
    items.push(
      <ActivityEvidenceList
        key={`${message.id}:media-evidence`}
        evidence={trailingEvidence}
      />,
    );
  }

  if (!items.length) return null;
  const group = describeActivityGroup(message, evidenceByLine, trailingEvidence);
  return (
    <ActivityGroup title={group.title} icon={group.icon}>
      {items}
    </ActivityGroup>
  );
}

function ActivityTraceRow({ line, active, evidence = [] }: { line: string; active: boolean; evidence?: ActivityEvidence[] }) {
  const trace = describeTraceLine(line);
  const Icon = trace.kind === "search"
    ? Search
    : trace.kind === "done"
      ? CheckCircle2
      : trace.kind === "tool"
        ? Wrench
        : Layers;
  return (
    <ActivityStep
      as="li"
      marker={<TraceIconMark trace={trace} fallbackIcon={Icon} active={active} />}
      active={active && trace.kind !== "done"}
      tone={trace.kind === "done" ? "success" : active ? "active" : "neutral"}
      label={trace.label}
      detail={trace.detail}
      title={`${trace.label}${trace.detail ? ` ${trace.detail}` : ""}`}
    >
      <ActivityEvidencePreview evidence={evidence} />
    </ActivityStep>
  );
}

function ActivityEvidenceList({ evidence }: { evidence: ActivityEvidence[] }) {
  return (
    <ul className="space-y-1">
      <ActivityStep
        as="li"
        icon={FileImage}
        tone="success"
        label={evidenceLabel(evidence)}
      >
        <ActivityEvidencePreview evidence={evidence} />
      </ActivityStep>
    </ul>
  );
}

function evidenceLabel(evidence: ActivityEvidence[]): string {
  const first = evidence[0]?.attachment.kind;
  if (first === "image") return evidence.length > 1 ? "Found images" : "Found image";
  if (first === "video") return evidence.length > 1 ? "Found videos" : "Found video";
  return evidence.length > 1 ? "Found files" : "Found file";
}

function toolEvidenceByTraceLine(message: UIMessage): Map<string, ActivityEvidence[]> {
  const map = new Map<string, ActivityEvidence[]>();
  for (const event of message.toolEvents ?? []) {
    const evidence = activityEvidenceFromToolEvent(event);
    if (!evidence.length) continue;
    const line = formatToolCallTrace(event);
    if (!line) continue;
    const existing = map.get(line) ?? [];
    map.set(line, [...existing, ...evidence]);
  }
  return map;
}

function allToolEvidence(evidenceByLine: Map<string, ActivityEvidence[]>): ActivityEvidence[] {
  return [...evidenceByLine.values()].flat();
}

function describeActivityGroup(
  message: UIMessage,
  evidenceByLine: Map<string, ActivityEvidence[]>,
  mediaEvidence: ActivityEvidence[],
): { title: string; icon: LucideIcon } {
  const names = [
    ...traceLines(message).map((line) => /^([a-zA-Z0-9_.-]+)\(/.exec(line.trim())?.[1] ?? line),
    ...(message.toolEvents ?? []).map(toolEventDisplayName),
  ].map((name) => name.toLowerCase());
  const evidence = [...allToolEvidence(evidenceByLine), ...mediaEvidence];
  const hasVisualEvidence = evidence.some((item) => item.attachment.kind === "image" || item.attachment.kind === "video");
  if (hasVisualEvidence && names.some((name) => /browser|screenshot|vision|image|video/.test(name))) {
    return { title: "Vision", icon: FileImage };
  }
  if (names.some((name) => /browser|screenshot/.test(name))) return { title: "Browser", icon: FileImage };
  if (names.some((name) => /web|search|fetch|read|open/.test(name))) return { title: "Web", icon: Search };
  if (names.some((name) => /exec|shell|terminal|bash|run_cli_app|cli_anything/.test(name))) return { title: "Shell", icon: Terminal };
  if (names.some((name) => /^mcp_|mcp/.test(name))) return { title: "MCP", icon: Server };
  if (message.fileEdits?.length) return { title: "Files", icon: Layers };
  if (evidence.length) return { title: "Media", icon: FileImage };
  return { title: "Working", icon: Layers };
}

function toolEventDisplayName(event: ToolProgressEvent): string {
  return typeof (event as { function?: { name?: unknown } }).function?.name === "string"
    ? String((event as { function?: { name?: unknown } }).function?.name)
    : typeof event.name === "string"
      ? event.name
      : "";
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
          "grid h-4 w-4 shrink-0 place-items-center overflow-hidden rounded-[4px] border border-border/45 bg-background shadow-[inset_0_0_0_1px_rgba(0,0,0,0.02)]",
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
        "h-3.5 w-3.5 shrink-0",
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
      label: "Command",
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
    <ActivityStep
      as="li"
      active={rowActive}
      tone={failed ? "error" : rowActive ? "active" : run.status === "done" ? "success" : "neutral"}
      title={`${label} @${run.name}${args ? ` ${args}` : ""}${run.error ? ` ${run.error}` : ""}`}
      label={label}
      marker={(
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
      )}
    >
      <div className="-mt-0.5 flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
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
      </div>
    </ActivityStep>
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
    <ActivityStep
      as="li"
      active={rowActive}
      tone={failed ? "error" : rowActive ? "active" : run.status === "done" ? "success" : "neutral"}
      title={`${label} ${displayName} ${run.toolName}${run.argsPreview ? ` ${run.argsPreview}` : ""}${run.error ? ` ${run.error}` : ""}`}
      label={label}
      marker={(
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
      )}
    >
      <div className="-mt-0.5 flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
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
      </div>
    </ActivityStep>
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
