import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ChevronRight, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";

import { FileReferenceChip } from "@/components/FileReferenceChip";
import { ReasoningBubble, StreamingLabelSheen, TraceGroup } from "@/components/MessageBubble";
import { cn } from "@/lib/utils";
import type { UIFileEdit, UIMessage } from "@/lib/types";

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
  fileCount: number;
  added: number;
  deleted: number;
  hasDiffStats: boolean;
  hasEditingFiles: boolean;
  hasFailedFiles: boolean;
  primaryFilePath?: string;
  primaryFileTooltipPath?: string;
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
  pending: boolean;
  error?: string;
}

function countActivity(messages: UIMessage[], fileEdits: FileEditSummary[]): ActivityCounts {
  let reasoningSteps = 0;
  let toolCalls = 0;
  for (const m of messages) {
    if (isReasoningOnlyAssistant(m)) {
      reasoningSteps += 1;
      continue;
    }
    if (m.kind === "trace") {
      const lines = m.traces?.length ?? (m.content.trim() ? 1 : 0);
      toolCalls += lines;
    }
  }
  let added = 0;
  let deleted = 0;
  let hasDiffStats = false;
  let hasEditingFiles = false;
  let failedFileCount = 0;
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
    fileCount: fileEdits.length,
    added,
    deleted,
    hasDiffStats,
    hasEditingFiles,
    hasFailedFiles: fileEdits.length > 0 && failedFileCount === fileEdits.length,
    primaryFilePath,
    primaryFileTooltipPath,
  };
}

interface AgentActivityClusterProps {
  messages: UIMessage[];
  /** True while the session turn is still running (drives “Working…” copy + header sheen). */
  isTurnStreaming: boolean;
  hasBodyBelow: boolean;
}

/**
 * Outer fold wrapping interleaved reasoning-only assistant rows and tool-trace rows.
 * Fixed max height with inner scroll; each block keeps its own small collapsible (reasoning / tools).
 */
export function AgentActivityCluster({
  messages,
  isTurnStreaming,
  hasBodyBelow,
}: AgentActivityClusterProps) {
  const { t } = useTranslation();
  const fileEdits = useMemo(
    () => summarizeFileEdits(collectFileEdits(messages), isTurnStreaming),
    [messages, isTurnStreaming],
  );
  const {
    reasoningSteps,
    toolCalls,
    fileCount,
    added,
    deleted,
    hasDiffStats,
    hasEditingFiles,
    hasFailedFiles,
    primaryFilePath,
    primaryFileTooltipPath,
  } = countActivity(messages, fileEdits);
  const hasPendingFileEdit = fileEdits.some((edit) => edit.pending);

  const [userToggledOuter, setUserToggledOuter] = useState(false);
  const [outerOpenLocal, setOuterOpenLocal] = useState(false);
  const activityScrollRef = useRef<HTMLDivElement>(null);
  const activityContentRef = useRef<HTMLDivElement>(null);
  const autoFollowActivityRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);
  /** Collapsed by default during “Working…” and after the turn; user expands to inspect traces. */
  const outerExpanded = userToggledOuter ? outerOpenLocal : false;

  const hasLiveEditingFiles = isTurnStreaming && hasEditingFiles;
  const headerBusy = fileCount > 0 ? hasEditingFiles : isTurnStreaming;
  const singleFilePath = fileCount === 1 ? primaryFilePath : undefined;
  const singleFileTooltipPath = fileCount === 1 ? primaryFileTooltipPath : undefined;
  const hasVisibleActivity = reasoningSteps > 0 || toolCalls > 0 || fileCount > 0;

  const fileActivitySummary = fileCount > 0
    ? hasPendingFileEdit && !singleFilePath
      ? t("message.fileActivityPreparing", { defaultValue: "Preparing edit…" })
      : singleFilePath
      ? t(fileActivitySummaryKey(hasLiveEditingFiles, hasFailedFiles), {
          file: shortFileName(singleFilePath),
          defaultValue: `${fileActivityVerb(hasLiveEditingFiles, hasFailedFiles)} {{file}}`,
        })
      : t(fileActivityManySummaryKey(hasLiveEditingFiles, hasFailedFiles), {
          count: fileCount,
          defaultValue: `${fileActivityVerb(hasLiveEditingFiles, hasFailedFiles)} {{count}} files`,
        })
    : "";

  const summary = fileCount > 0
    ? fileActivitySummary
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

  const onActivityScroll = useCallback(() => {
    const el = activityScrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    autoFollowActivityRef.current = distance < ACTIVITY_SCROLL_NEAR_BOTTOM_PX;
  }, []);

  if (!hasVisibleActivity) return null;

  return (
    <div className={cn("w-full", hasBodyBelow && "mb-2")}>
      <button
        type="button"
        onClick={toggleOuter}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={outerExpanded}
        aria-label={summary}
      >
        <Layers className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-left">
          {singleFilePath ? (
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <StreamingLabelSheen
                active={headerBusy}
                className="shrink-0"
              >
                {fileActivityVerb(hasLiveEditingFiles, hasFailedFiles)}
              </StreamingLabelSheen>
              <FileReferenceChip
                path={singleFilePath}
                tooltipPath={singleFileTooltipPath}
                active={hasLiveEditingFiles}
                className="-my-0.5 min-w-0"
                textClassName="text-xs"
                testId="activity-header-file-reference"
              />
            </span>
          ) : (
            <StreamingLabelSheen
              active={headerBusy}
              className="min-w-0"
            >
              {summary}
            </StreamingLabelSheen>
          )}
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
            "mt-1 overflow-hidden rounded-md border border-border/50 bg-muted/25",
          )}
        >
          <div
            ref={activityScrollRef}
            data-testid="agent-activity-scroll"
            onScroll={onActivityScroll}
            className={cn(
              CLUSTER_SCROLL_MAX_CLASS,
              "overflow-y-auto px-2 py-1.5 scrollbar-thin scrollbar-track-transparent",
            )}
          >
            <div ref={activityContentRef} className="flex flex-col gap-2">
              {messages.map((m) => {
                if (isReasoningOnlyAssistant(m)) {
                  return (
                    <ReasoningBubble
                      key={m.id}
                      text={m.reasoning ?? ""}
                      streaming={isTurnStreaming && !!m.reasoningStreaming}
                      hasBodyBelow={false}
                      embeddedInCluster
                    />
                  );
                }
                if (m.kind === "trace") {
                  const hasTraceLines = (m.traces?.length ?? 0) > 0 || m.content.trim().length > 0;
                  return hasTraceLines ? (
                    <div key={m.id} className="flex flex-col gap-1">
                      <TraceGroup message={m} animClass="" />
                    </div>
                  ) : null;
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

function shortFileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function fileActivityVerb(editing: boolean, failed: boolean): string {
  if (failed) return "Failed";
  return editing ? "Editing" : "Edited";
}

function fileActivitySummaryKey(editing: boolean, failed: boolean): string {
  if (failed) return "message.fileActivityFailedOne";
  return editing ? "message.fileActivityEditingOne" : "message.fileActivityEditedOne";
}

function fileActivityManySummaryKey(editing: boolean, failed: boolean): string {
  if (failed) return "message.fileActivityFailedMany";
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
      pending: summary.pending && !summary.path,
      error: summary.error,
    }];
  });
}

function hasVisibleDiffStats(edit: Pick<FileEditSummary, "added" | "deleted">): boolean {
  return edit.added > 0 || edit.deleted > 0;
}

function FileEditGroup({ edits }: { edits: FileEditSummary[] }) {
  if (edits.length === 0) return null;
  return (
    <ul className="space-y-1 border-l border-muted-foreground/15 pl-3">
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
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-1.5 text-xs">
      <div className="flex min-w-0 items-center gap-2">
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
          <span className="inline-flex shrink-0 items-center gap-1 text-[10.5px] font-medium text-destructive/75">
            <AlertCircle className="h-3 w-3" aria-hidden />
            {t("message.fileEditFailed", { defaultValue: "Failed" })}
          </span>
        ) : null}
        {edit.approximate && !failed ? (
          <span className="shrink-0 text-[10.5px] font-medium text-muted-foreground/55">
            {t("message.fileEditApproximate", { defaultValue: "estimated" })}
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
    <span className="inline-flex shrink-0 translate-y-[0.055em] items-center gap-1.5 tabular-nums">
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
    <span className={cn("inline-flex", className)} aria-label={`${sign}${safeValue}`}>
      <span className="inline-flex" aria-hidden>
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
    <span className="inline-flex h-[1em] overflow-hidden align-[-0.13em]" aria-hidden>
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
    <span className="relative inline-block h-[1em] w-[0.62em] overflow-hidden">
      <span
        className="flex flex-col transition-transform duration-200 ease-out will-change-transform"
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
