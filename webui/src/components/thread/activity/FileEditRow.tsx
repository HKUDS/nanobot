import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleDashed,
  ExternalLink,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { FileReferenceChip } from "@/components/FileReferenceChip";
import {
  hasRenderableFileDiff,
  parseRenderableFileDiff,
  type RenderableFileDiff,
  type RenderableFileDiffHunk,
} from "@/lib/file-diff";
import { codeLanguageFromPath } from "@/lib/code-language";
import type { FileEditDisplayMode } from "@/lib/local-preferences";
import type { UIFileDiff, UIFileEdit } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ActivityStep } from "./ActivityStep";
import { DiffPair } from "./DiffPair";
import { DiffSyntaxHighlight } from "./DiffSyntaxHighlight";

const INITIAL_VISIBLE_DIFF_LINES = 160;
const AUTO_COLLAPSE_DIFF_LINES = INITIAL_VISIBLE_DIFF_LINES;

type DiffFileEditDisplayMode = Exclude<FileEditDisplayMode, "summary">;

interface VisibleDiffHunk {
  hunk: RenderableFileDiffHunk;
  skippedBefore: number;
}

interface VisibleDiff {
  hunks: VisibleDiffHunk[];
  hiddenLineCount: number;
}

const EMPTY_VISIBLE_DIFF: VisibleDiff = { hunks: [], hiddenLineCount: 0 };

export interface FileEditSummary {
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
  diff?: UIFileDiff;
}

export function FileEditGroup({
  edits,
  displayMode,
  onOpenFilePreview,
  density = "default",
}: {
  edits: FileEditSummary[];
  displayMode: FileEditDisplayMode;
  onOpenFilePreview?: (path: string) => void;
  density?: "default" | "diff-only";
}) {
  if (edits.length === 0) return null;
  return (
    <ul className="space-y-1">
      {edits.map((edit) => {
        if (density === "diff-only" && canRenderDiff(edit, displayMode)) {
          return (
            <FileEditDiffOnly
              key={edit.key}
              edit={edit}
              displayMode={displayMode}
              onOpenFilePreview={onOpenFilePreview}
            />
          );
        }
        return (
          <FileEditRow
            key={edit.key}
            edit={edit}
            displayMode={displayMode}
            onOpenFilePreview={onOpenFilePreview}
          />
        );
      })}
    </ul>
  );
}

function canRenderDiff(
  edit: FileEditSummary,
  displayMode: FileEditDisplayMode,
): displayMode is DiffFileEditDisplayMode {
  return (
    displayMode !== "summary"
    && edit.status !== "editing"
    && edit.status !== "error"
    && hasRenderableFileDiff(edit.diff)
  );
}

function FileEditDiffOnly({
  edit,
  displayMode,
  onOpenFilePreview,
}: {
  edit: FileEditSummary;
  displayMode: DiffFileEditDisplayMode;
  onOpenFilePreview?: (path: string) => void;
}) {
  return (
    <li className="min-w-0 py-0.5">
      <FileUnifiedDiff
        diff={edit.diff!}
        collapsed={displayMode === "collapsed_diff"}
        added={edit.added}
        deleted={edit.deleted}
        showCollapsedStats={false}
        previewPath={edit.absolute_path || edit.path}
        onOpenFilePreview={onOpenFilePreview}
      />
    </li>
  );
}

function FileEditRow({
  edit,
  displayMode,
  onOpenFilePreview,
}: {
  edit: FileEditSummary;
  displayMode: FileEditDisplayMode;
  onOpenFilePreview?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const editing = edit.status === "editing";
  const failed = edit.status === "error";
  const hasCountedDiff = !failed && !edit.binary && hasVisibleDiffStats(edit);
  const showDiff = canRenderDiff(edit, displayMode);
  const rawFailureDetail = failed ? cleanFileEditError(edit.error) : "";
  const failureDetail = failed
    ? formatFileEditError(edit.error)
      || t("message.fileEditFailedFallback", { defaultValue: "File change was not applied." })
    : "";
  const statusIcon = failed ? (
    <AlertCircle className="h-3 w-3" aria-hidden />
  ) : editing ? (
    <CircleDashed className="h-3 w-3 animate-spin" aria-hidden />
  ) : (
    <CheckCircle2 className="h-3 w-3" aria-hidden />
  );
  return (
    <ActivityStep
      as="li"
      marker={(
        <span
          className={cn(
            "grid h-3.5 w-3.5 place-items-center rounded-full border bg-background transition-colors",
            failed && "border-destructive/30 text-destructive/78",
            editing && "border-muted-foreground/24 text-muted-foreground/65",
            !failed && !editing && "border-emerald-500/28 text-emerald-500/78",
          )}
        >
          {statusIcon}
        </span>
      )}
      active={editing}
      tone={failed ? "error" : editing ? "active" : "success"}
      className="text-xs"
      contentClassName={failed || showDiff ? "min-w-0" : "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3"}
      title={rawFailureDetail || edit.absolute_path || edit.path}
      label={edit.pending && !edit.path
        ? t("message.fileEditPreparing", { defaultValue: "Preparing file edit…" })
        : (
          <FileReferenceChip
            path={edit.path}
            tooltipPath={edit.absolute_path}
            previewPath={edit.absolute_path || edit.path}
            onOpen={onOpenFilePreview}
            display="path"
            active={editing}
            className="min-w-0"
            textClassName="text-[12px]"
            testId="activity-file-reference"
          />
        )}
      detail={null}
      aside={hasCountedDiff ? <DiffPair added={edit.added} deleted={edit.deleted} /> : null}
    >
      {failed ? (
        <span className="block max-w-[42rem] truncate text-[11px] leading-4 text-destructive/75">
          {failureDetail}
        </span>
      ) : null}
      {showDiff ? (
        <FileUnifiedDiff
          diff={edit.diff!}
          collapsed={displayMode === "collapsed_diff"}
          added={edit.added}
          deleted={edit.deleted}
          previewPath={edit.absolute_path || edit.path}
          onOpenFilePreview={onOpenFilePreview}
        />
      ) : null}
    </ActivityStep>
  );
}

export function hasVisibleDiffStats(edit: Pick<FileEditSummary, "added" | "deleted">): boolean {
  return edit.added > 0 || edit.deleted > 0;
}

function cleanFileEditError(error?: string): string {
  const firstLine = (error || "").replace(/\s+/g, " ").trim();
  if (!firstLine) return "";
  return firstLine
    .replace(/^Error applying patch:\s*/i, "")
    .replace(/^Error writing file:\s*/i, "")
    .replace(/^Error editing file:\s*/i, "")
    .replace(/^Error:\s*/i, "");
}

function formatFileEditError(error?: string): string {
  const cleaned = cleanFileEditError(error);
  if (!cleaned) return "";

  if (/\bpermission denied\b/i.test(cleaned) || /\boperation not permitted\b/i.test(cleaned)) {
    return "No permission to change this location.";
  }

  return cleaned
    .replace(/^old_text not found in (.+)$/i, "Target text was not found in $1.")
    .replace(/^old_text appears multiple times in (.+)$/i, "Target text matched multiple places in $1.")
    .replace(/^file to (?:update|delete) does not exist: (.+)$/i, "File does not exist: $1.")
    .replace(/^path to (?:update|delete) is not a file: (.+)$/i, "Path is not a file: $1.")
    .slice(0, 180);
}

function FileUnifiedDiff({
  diff,
  collapsed,
  added,
  deleted,
  showCollapsedStats = true,
  previewPath,
  onOpenFilePreview,
}: {
  diff: UIFileDiff;
  collapsed: boolean;
  added: number;
  deleted: number;
  showCollapsedStats?: boolean;
  previewPath?: string;
  onOpenFilePreview?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [open, setOpen] = useState(false);
  const [expandedLines, setExpandedLines] = useState(false);
  const renderableDiff = useMemo(() => parseRenderableFileDiff(diff), [diff]);
  const language = useMemo(() => codeLanguageFromPath(previewPath), [previewPath]);
  const totalLineCount = useMemo(() => countDiffLines(renderableDiff), [renderableDiff]);
  const shouldAutoCollapse = totalLineCount > AUTO_COLLAPSE_DIFF_LINES || !!diff.truncated;
  const startsCollapsed = collapsed || shouldAutoCollapse;
  const shouldRenderBody = !startsCollapsed || open;
  const shouldLimitLines = totalLineCount > INITIAL_VISIBLE_DIFF_LINES;
  const lineLimit = expandedLines || !shouldLimitLines
    ? totalLineCount
    : INITIAL_VISIBLE_DIFF_LINES;
  const visibleDiff = useMemo(
    () => shouldRenderBody
      ? selectVisibleDiffLines(renderableDiff, lineLimit, totalLineCount)
      : EMPTY_VISIBLE_DIFF,
    [lineLimit, renderableDiff, shouldRenderBody, totalLineCount],
  );
  const lineCountLabel = t("message.fileEditDiffLineCount", {
    count: diff.truncated ? `${totalLineCount}+` : totalLineCount,
    defaultValue: "{{count}} lines",
  });
  const viewDiffLabel = shouldAutoCollapse
    ? tx("message.fileEditViewLargeDiff", "View large diff")
    : tx("message.fileEditViewDiff", "View diff");

  useEffect(() => {
    setOpen(false);
    setExpandedLines(false);
  }, [diff]);

  const handleToggleOpen = () => {
    if (open) setExpandedLines(false);
    setOpen(!open);
  };

  if (totalLineCount === 0) return null;

  const renderBody = () => (
    <div
      className="mt-1 overflow-hidden rounded-md border border-border/55 bg-background/80 shadow-[0_1px_0_rgba(15,23,42,0.03)]"
      data-testid="file-edit-diff"
    >
      {visibleDiff.hunks.map(({ hunk, skippedBefore }, index) => (
        <div
          key={`${hunk.old_start}-${hunk.new_start}-${index}`}
          className={cn("min-w-0", index > 0 && "border-t border-border/45")}
        >
          {skippedBefore > 0 ? <DiffHunkGap lineCount={skippedBefore} /> : null}
          <div className="overflow-x-auto">
            <DiffSyntaxHighlight language={language} lines={hunk.lines} />
          </div>
        </div>
      ))}
      {visibleDiff.hiddenLineCount > 0 ? (
        <div className="border-t border-border/45 bg-muted/30 px-2 py-1">
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1 rounded px-1 py-0.5 text-[11px] font-medium",
              "text-muted-foreground transition-colors hover:bg-muted/65 hover:text-foreground",
            )}
            data-testid="file-edit-diff-expand-lines"
            onClick={() => setExpandedLines(true)}
          >
            <ChevronDown className="h-3 w-3" aria-hidden />
            {t("message.fileEditShowMoreLines", {
              count: visibleDiff.hiddenLineCount,
              defaultValue: "Show {{count}} more lines",
            })}
          </button>
        </div>
      ) : expandedLines && shouldLimitLines ? (
        <div className="border-t border-border/45 bg-muted/30 px-2 py-1">
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1 rounded px-1 py-0.5 text-[11px] font-medium",
              "text-muted-foreground transition-colors hover:bg-muted/65 hover:text-foreground",
            )}
            data-testid="file-edit-diff-collapse-lines"
            onClick={() => setExpandedLines(false)}
          >
            <ChevronUp className="h-3 w-3" aria-hidden />
            {tx("message.fileEditShowFewerLines", "Show fewer lines")}
          </button>
        </div>
      ) : null}
      {diff.truncated ? (
        <div
          className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border/45 bg-muted/35 px-2 py-1 text-[11px] text-muted-foreground"
          data-testid="file-edit-diff-truncated"
        >
          <span>
            {tx("message.fileEditDiffTruncated", "Diff truncated. Open the file for the full change.")}
          </span>
          {previewPath && onOpenFilePreview ? (
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1 rounded px-1 py-0.5 font-medium",
                "text-muted-foreground transition-colors hover:bg-muted/65 hover:text-foreground",
              )}
              data-testid="file-edit-diff-open-file"
              onClick={() => onOpenFilePreview(previewPath)}
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              {tx("message.fileEditOpenFile", "Open file")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  if (!startsCollapsed) return renderBody();

  return (
    <div className="mt-1">
      <button
        type="button"
        aria-expanded={open}
        data-testid="file-edit-diff-toggle"
        onClick={handleToggleOpen}
        className={cn(
          "flex w-full cursor-pointer items-center gap-2 rounded-md border border-border/45 bg-muted/35 px-2 py-1 text-left",
          "text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted/50",
        )}
      >
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span className="min-w-0 flex-1">{viewDiffLabel}</span>
        <span className="shrink-0 text-muted-foreground/65">{lineCountLabel}</span>
        {showCollapsedStats ? <DiffPair added={added} deleted={deleted} /> : null}
      </button>
      {open ? renderBody() : null}
    </div>
  );
}

function countDiffLines(diff: RenderableFileDiff): number {
  return diff.hunks.reduce((total, hunk) => total + hunk.lines.length, 0);
}

function selectVisibleDiffLines(
  diff: RenderableFileDiff,
  lineLimit: number,
  totalLineCount: number,
): VisibleDiff {
  if (lineLimit >= totalLineCount) {
    return {
      hunks: diff.hunks.map((hunk, index) => ({
        hunk,
        skippedBefore: index > 0 ? countSkippedUnchangedLines(diff.hunks[index - 1], hunk) : 0,
      })),
      hiddenLineCount: 0,
    };
  }

  let remaining = Math.max(0, lineLimit);
  const hunks: VisibleDiffHunk[] = [];
  let previousHunk: RenderableFileDiffHunk | null = null;
  for (const hunk of diff.hunks) {
    if (remaining <= 0) break;
    const skippedBefore = previousHunk ? countSkippedUnchangedLines(previousHunk, hunk) : 0;
    if (hunk.lines.length <= remaining) {
      hunks.push({ hunk, skippedBefore });
      remaining -= hunk.lines.length;
      previousHunk = hunk;
      continue;
    }
    hunks.push({ hunk: { ...hunk, lines: hunk.lines.slice(0, remaining) }, skippedBefore });
    remaining = 0;
    previousHunk = hunk;
  }
  return {
    hunks,
    hiddenLineCount: Math.max(0, totalLineCount - lineLimit),
  };
}

function countSkippedUnchangedLines(
  previous: RenderableFileDiffHunk,
  current: RenderableFileDiffHunk,
): number {
  const oldGap = current.old_start - (previous.old_start + previous.old_lines);
  const newGap = current.new_start - (previous.new_start + previous.new_lines);
  return Math.max(0, oldGap, newGap);
}

function DiffHunkGap({ lineCount }: { lineCount: number }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-center gap-2 bg-muted/35 px-2 py-1 text-[11px] text-muted-foreground"
      data-testid="file-edit-diff-hunk-gap"
    >
      <span
        className="select-none rounded border border-border/45 bg-background/70 px-1 font-mono text-muted-foreground/70"
        aria-hidden
      >
        ...
      </span>
      <span>
        {t("message.fileEditUnchangedLinesHidden", {
          count: lineCount,
          defaultValue: "{{count}} unchanged lines hidden",
        })}
      </span>
    </div>
  );
}
