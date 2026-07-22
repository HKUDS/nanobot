import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CheckCircle2,
  Clock3,
  Layers,
  Search,
  Server,
  Terminal,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { cliAppInitials, mcpPresetInitials } from "@/components/CliAppMentionText";
import { ActivityStep } from "@/components/thread/activity/ActivityStep";
import { coalesceActivityMessages } from "@/components/thread/activity/activity-message-model";
import {
  compactActivityPath,
  redactShellCommand,
} from "@/components/thread/activity/activity-text";
import { FileEditGroup, type FileEditSummary } from "@/components/thread/activity/FileEditRow";
import { GenericToolRun } from "@/components/thread/activity/GenericToolRun";
import {
  canGroupGenericToolRuns,
  type GenericToolRunItem,
  type GenericToolStatus,
  parseGenericToolTrace,
} from "@/components/thread/activity/generic-tool-model";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import { describeMcpActivity } from "@/components/thread/activity/mcp-activity-model";
import { ThinkingReasoningShell } from "@/components/thread/activity/ThinkingReasoningShell";
import { WebActivityRow } from "@/components/thread/activity/WebActivityRow";
import {
  describeTraceLine,
  type TraceDescription,
} from "@/components/thread/activity/trace-activity-model";
import { WebSearchRun } from "@/components/thread/activity/WebSearchRun";
import { webSearchRunsByTraceLine } from "@/components/thread/activity/web-search-model";
import {
  isAgentActivityMember,
  isReasoningOnlyAssistant,
} from "@/lib/activity-timeline";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import { canonicalToolTrace, formatToolCallTrace } from "@/lib/tool-traces";
import { cn } from "@/lib/utils";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import type { CliAppInfo, McpPresetInfo, ToolProgressEvent, UIFileEdit, UIMessage } from "@/lib/types";

const ACTIVITY_SCROLL_NEAR_BOTTOM_PX = 24;

export { isAgentActivityMember, isReasoningOnlyAssistant };

interface ActivityCounts {
  reasoningSteps: number;
  toolCalls: number;
  cliCount: number;
  mcpCount: number;
  fileCount: number;
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
  args: unknown;
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
  return {
    reasoningSteps,
    toolCalls,
    cliCount,
    mcpCount,
    fileCount: fileEdits.length,
  };
}

interface AgentActivityClusterProps {
  messages: UIMessage[];
  /** True while the session turn is still running (drives “Working…” copy + header sheen). */
  isTurnStreaming: boolean;
  hasBodyBelow: boolean;
  /** Persisted end-to-end turn latency from the assistant answer, used for history replay. */
  turnLatencyMs?: number;
  /** User turn start timestamp for live activity before the first trace/reasoning row. */
  startedAtMs?: number;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  onOpenFilePreview?: (path: string) => void;
}

/**
 * Outer fold wrapping interleaved reasoning-only assistant rows and tool-trace rows.
 * Fixed max height with inner scroll and a single flat list of activity rows.
 */
export function AgentActivityCluster({
  messages,
  isTurnStreaming,
  hasBodyBelow,
  turnLatencyMs,
  startedAtMs,
  cliApps = [],
  mcpPresets = [],
  onOpenFilePreview,
}: AgentActivityClusterProps) {
  const { t } = useTranslation();
  const pageVisible = usePageVisibility();
  const activityMessages = useMemo(() => coalesceActivityMessages(messages), [messages]);
  const fileEdits = useMemo(
    () => summarizeFileEdits(collectFileEdits(activityMessages), isTurnStreaming),
    [activityMessages, isTurnStreaming],
  );
  const cliRuns = useMemo(() => collectCliRuns(activityMessages), [activityMessages]);
  const mcpRuns = useMemo(() => collectMcpRuns(activityMessages), [activityMessages]);
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
  } = countActivity(activityMessages, fileEdits, cliRuns, mcpRuns);

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

  const hasVisibleActivity = reasoningSteps > 0 || toolCalls > 0 || cliCount > 0 || mcpCount > 0 || fileCount > 0;
  const hasOnlyFileActivity = fileCount > 0 && activityMessages.every(messageHasOnlyFileActivity);
  const hasNonReasoningActivity = toolCalls > 0 || cliCount > 0 || mcpCount > 0 || fileCount > 0;
  const durationMs = activityDurationMs(
    activityMessages,
    isTurnStreaming,
    now,
    turnLatencyMs,
    startedAtMs,
  );
  const activityDuration = formatActivityDuration(durationMs);
  const thoughtLabel = hasNonReasoningActivity
    ? isTurnStreaming
      ? t("message.activityWorkingFor", {
          duration: activityDuration,
          defaultValue: "Working for {{duration}}",
        })
      : durationMs <= 0
        ? t("message.activityWorked", { defaultValue: "Worked" })
      : t("message.activityWorkedFor", {
          duration: activityDuration,
          defaultValue: "Worked for {{duration}}",
        })
    : isTurnStreaming
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
  }, [outerExpanded, activityMessages, isTurnStreaming, scheduleActivityScrollToBottom]);

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
    if (!isTurnStreaming || !pageVisible) return undefined;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [isTurnStreaming, pageVisible]);

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
      <div className={cn("w-full", hasBodyBelow && "mb-2")}>
        <FileEditGroup
          edits={fileEdits}
          onOpenFilePreview={onOpenFilePreview}
        />
      </div>
    );
  }

  return (
    <div className={cn("w-full", hasBodyBelow && "mb-2")}>
      <ThinkingReasoningShell
        active={isTurnStreaming}
        expanded={outerExpanded}
        label={thoughtLabel}
        viewportRef={activityScrollRef}
        contentRef={activityContentRef}
        onToggle={toggleOuter}
        onScroll={onActivityScroll}
      >
        <ActivityMessageTimeline
          messages={activityMessages}
          active={isTurnStreaming}
          cliAppsByName={cliAppsByName}
          mcpPresetsByName={mcpPresetsByName}
        />
        {fileEdits.length ? (
          <FileEditGroup
            edits={fileEdits}
            onOpenFilePreview={onOpenFilePreview}
          />
        ) : null}
      </ThinkingReasoningShell>
    </div>
  );
}

function messageHasOnlyFileActivity(message: UIMessage): boolean {
  if (message.kind !== "trace" || !message.fileEdits?.length) return false;
  return traceLines(message).every((line) => !line.trim() || isFileEditTraceLine(line));
}

function activityDurationMs(
  messages: UIMessage[],
  active: boolean,
  now: number,
  completedLatencyMs?: number,
  activeStartedAtMs?: number,
): number {
  if (!active && Number.isFinite(completedLatencyMs) && completedLatencyMs! >= 0) {
    return Math.round(completedLatencyMs!);
  }
  const timestamps = messages
    .map((message) => message.createdAt)
    .filter((value) => Number.isFinite(value));
  if (!timestamps.length) return 0;
  const first = active && Number.isFinite(activeStartedAtMs)
    ? activeStartedAtMs!
    : Math.min(...timestamps);
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

function ActivityMessageTimeline({
  messages,
  active,
  cliAppsByName,
  mcpPresetsByName,
}: {
  messages: UIMessage[];
  active: boolean;
  cliAppsByName: Map<string, CliAppInfo>;
  mcpPresetsByName: Map<string, McpPresetInfo>;
}) {
  const items: ReactNode[] = [];

  messages.forEach((message, index) => {
    if (isReasoningOnlyAssistant(message)) {
      items.push(
        <ReasoningRow
          key={message.id}
          text={message.reasoning ?? ""}
          streaming={active && !!message.reasoningStreaming}
        />,
      );
      return;
    }
    if (message.kind === "trace") {
      items.push(
        <ActivityTraceTimeline
          key={message.id}
          message={message}
          active={active && index === messages.length - 1}
          cliAppsByName={cliAppsByName}
          mcpPresetsByName={mcpPresetsByName}
        />,
      );
    }
  });
  return <>{items}</>;
}

function ActivityTraceList({
  lines,
  active,
  stateByLine,
}: {
  lines: string[];
  active: boolean;
  stateByLine?: Map<string, GenericToolState>;
}) {
  const items: ReactNode[] = [];
  let genericItems: GenericToolRunItem[] = [];

  const flushGenericItems = (suffix: string) => {
    if (!genericItems.length) return;
    items.push(
      <GenericToolRun
        key={`generic-tool:${genericItems[0].trace.groupKey}:${suffix}`}
        items={genericItems}
      />,
    );
    genericItems = [];
  };

  lines.forEach((line, index) => {
    const trace = parseGenericToolTrace(line);
    if (trace) {
      const key = canonicalToolTrace(line);
      const explicitState = stateByLine?.get(key);
      const fallbackStatus: GenericToolStatus = active && index === lines.length - 1 ? "running" : "done";
      const item: GenericToolRunItem = {
        trace,
        status: explicitState?.status === "running" && !active ? "done" : explicitState?.status ?? fallbackStatus,
        error: explicitState?.error,
      };
      const previous = genericItems[genericItems.length - 1];
      if (previous && !canGroupGenericToolRuns(previous, item)) flushGenericItems(String(index));
      genericItems.push(item);
      return;
    }

    flushGenericItems(String(index));
    items.push(
      <ActivityTraceRow
        key={`${line}-${index}`}
        line={line}
        active={active && index === lines.length - 1}
        state={stateByLine?.get(canonicalToolTrace(line))}
      />,
    );
  });
  flushGenericItems("tail");

  return (
    <>
      {items}
    </>
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
  const webSearchRunsByLine = webSearchRunsByTraceLine(message.toolEvents ?? []);
  const genericStateByLine = genericToolStateByTraceLine(message);
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
        stateByLine={genericStateByLine}
      />,
    );
    normalLines = [];
  };

  lines.forEach((line, index) => {
    const traceKey = canonicalToolTrace(line);
    const webSearchRun = webSearchRunsByLine.get(traceKey);
    if (webSearchRun) {
      flushNormalLines(String(index));
      renderedRunKeys.add(webSearchRun.key);
      items.push(
        <WebSearchRun
          key={`${message.id}:web-search:${webSearchRun.key}:${index}`}
          run={webSearchRun}
          turnActive={active}
        />,
      );
      return;
    }

    const cliRun = cliRunsByLine.get(traceKey) ?? parseCliRunTrace(line);
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

    const mcpRun = mcpRunsByLine.get(traceKey) ?? parseMcpRunTrace(line);
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

  for (const run of webSearchRunsByLine.values()) {
    if (renderedRunKeys.has(run.key)) continue;
    items.push(
      <WebSearchRun
        key={`${message.id}:web-search:${run.key}:event`}
        run={run}
        turnActive={active}
      />,
    );
  }
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

  if (!items.length) return null;
  return (
    <>
      {items}
    </>
  );
}

function ActivityTraceRow({
  line,
  active,
  state,
}: {
  line: string;
  active: boolean;
  state?: GenericToolState;
}) {
  const status = state?.status ?? (active ? "running" : "done");
  const trace = describeTraceLine(line, status, state?.result);
  const rowActive = status === "running" && active;
  const Icon = trace.icon === "clock" ? Clock3 : (trace.kind === "search"
    ? Search
    : trace.kind === "done"
      ? CheckCircle2
      : trace.kind === "tool"
        ? Wrench
        : Layers);
  if (trace.url && trace.host) {
    return (
      <WebActivityRow
        title={trace.label}
        href={trace.url}
        host={trace.host}
        displayUrl={trace.detail}
        active={rowActive}
        tone={status === "error" ? "error" : status === "done" ? "success" : "active"}
      />
    );
  }
  return (
    <ActivityStep
      marker={<TraceIconMark trace={trace} fallbackIcon={Icon} active={rowActive} />}
      active={rowActive && trace.kind !== "done"}
      tone={status === "error" ? "error" : status === "done" ? "success" : "active"}
      label={[trace.label, trace.detail].filter(Boolean).join(" ")}
    />
  );
}

interface GenericToolState {
  status: GenericToolStatus;
  error?: string;
  result?: unknown;
}

const GENERIC_TOOL_STATUS_RANK: Record<GenericToolStatus, number> = { running: 1, done: 2, error: 3 };

function genericToolStateByTraceLine(message: UIMessage): Map<string, GenericToolState> {
  const map = new Map<string, GenericToolState>();
  for (const event of message.toolEvents ?? []) {
    const line = formatToolCallTrace(event);
    if (!line) continue;
    const key = canonicalToolTrace(line);
    const status: GenericToolStatus = event.phase === "error"
      ? "error"
      : event.phase === "end"
        ? "done"
        : "running";
    const next = {
      status,
      error: status === "error" ? toolProgressError(event.error) : undefined,
      result: event.result,
    };
    const previous = map.get(key);
    if (!previous || GENERIC_TOOL_STATUS_RANK[next.status] >= GENERIC_TOOL_STATUS_RANK[previous.status]) {
      map.set(key, next);
    }
  }
  return map;
}

function toolProgressError(error: unknown): string | undefined {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    try {
      return JSON.stringify(error);
    } catch {
      return "Tool call failed";
    }
  }
  return undefined;
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
    const key = canonicalToolTrace(line);
    runsByLine.set(key, mergeCliRun(runsByLine.get(key), run));
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
  const productName = PRODUCT_NAME_OVERRIDES[name.toLowerCase()];
  if (productName) return productName;
  return name
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ") || name;
}

const PRODUCT_NAME_OVERRIDES: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  openai: "OpenAI",
};

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
    args: argsObject,
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
    const key = canonicalToolTrace(line);
    runsByLine.set(key, mergeMcpRun(runsByLine.get(key), run));
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

function fileEditCallKey(edit: UIFileEdit): string {
  if (edit.call_id && edit.path) return `${edit.call_id}|${edit.tool}|${edit.path}`;
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
  return latestFileEditEvents(edits).flatMap((edit) => {
    const editing = active && edit.status === "editing";
    const failed = edit.status === "error";
    if (!edit.path && edit.pending && !editing) return [];
    if (!edit.path && !editing && !failed) return [];

    const status: UIFileEdit["status"] = editing
      ? "editing"
      : failed
        ? "error"
        : "done";
    const binary = !!edit.binary;
    return [{
      key: fileEditCallKey(edit),
      path: edit.path || "",
      absolute_path: edit.absolute_path,
      added: binary ? 0 : edit.added,
      deleted: binary ? 0 : edit.deleted,
      approximate: active && !!edit.approximate,
      binary,
      status,
      operation: edit.operation,
      pending: !!edit.pending && !edit.path,
      error: edit.error,
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
    <>
      {runs.map((run) => (
        <CliRunRow
          key={run.key}
          run={run}
          active={active}
          app={cliAppsByName.get(run.name.toLowerCase())}
        />
      ))}
    </>
  );
}

function CliRunRow({ run, active, app }: { run: CliRunSummary; active: boolean; app?: CliAppInfo }) {
  const args = compactActivityPath(redactShellCommand(formatCliArgs(run)));
  const failed = run.status === "error";
  const rowActive = active && run.status === "running";
  const color = failed ? "#DC2626" : app?.brand_color || "#0891B2";
  const logoUrls = useMemo(() => logoFallbackUrls(app?.logo_url), [app?.logo_url]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const displayName = app?.display_name || titleFromPresetName(run.name);
  const action = failed ? "Could not use" : rowActive ? "Using" : "Used";
  const label = `${action} ${displayName}${args ? ` · ${args}` : ""}`;

  return (
    <ActivityStep
      active={rowActive}
      tone={failed ? "error" : rowActive ? "active" : run.status === "done" ? "success" : "neutral"}
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
              decoding="async"
              loading="lazy"
              className="h-[78%] w-[78%] object-contain"
              onLoad={onLogoLoad}
              onError={onLogoError}
            />
          ) : app ? (
            cliAppInitials(app).slice(0, 2)
          ) : (
            <Terminal className="h-3 w-3" aria-hidden />
          )}
        </span>
      )}
    />
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
    <>
      {runs.map((run) => (
        <McpRunRow
          key={run.key}
          run={run}
          active={active}
          preset={mcpPresetsByName.get(run.presetName.toLowerCase())}
        />
      ))}
    </>
  );
}

function McpRunRow({ run, active, preset }: { run: McpRunSummary; active: boolean; preset?: McpPresetInfo }) {
  const failed = run.status === "error";
  const rowActive = active && run.status === "running";
  const color = failed ? "#DC2626" : preset?.brand_color || "#6D5DF6";
  const logoUrls = useMemo(() => logoFallbackUrls(preset?.logo_url), [preset?.logo_url]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const displayName = preset?.display_name || run.displayName;
  const activity = describeMcpActivity(
    run.toolName,
    run.args,
    failed ? "error" : rowActive ? "running" : "done",
  );
  const label = `${activity.action}${activity.target ? ` ${activity.target}` : ""} · ${displayName}`;

  return (
    <ActivityStep
      active={rowActive}
      tone={failed ? "error" : rowActive ? "active" : run.status === "done" ? "success" : "neutral"}
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
              decoding="async"
              loading="lazy"
              className="h-[78%] w-[78%] object-contain"
              onLoad={onLogoLoad}
              onError={onLogoError}
            />
          ) : preset ? (
            mcpPresetInitials(preset).slice(0, 2)
          ) : (
            <Server className="h-3 w-3" aria-hidden />
          )}
        </span>
      )}
    />
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
