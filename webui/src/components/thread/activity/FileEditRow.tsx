import { AlertCircle, CheckCircle2, CircleDashed } from "lucide-react";
import { useTranslation } from "react-i18next";

import { FileReferenceChip } from "@/components/FileReferenceChip";
import type { UIFileEdit } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ActivityStep } from "./ActivityStep";
import { DiffPair } from "./DiffPair";

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
}

export function FileEditGroup({
  edits,
  onOpenFilePreview,
}: {
  edits: FileEditSummary[];
  onOpenFilePreview?: (path: string) => void;
}) {
  if (edits.length === 0) return null;
  return (
    <ul className="space-y-1">
      {edits.map((edit) => (
        <FileEditRow
          key={edit.key}
          edit={edit}
          onOpenFilePreview={onOpenFilePreview}
        />
      ))}
    </ul>
  );
}

function FileEditRow({
  edit,
  onOpenFilePreview,
}: {
  edit: FileEditSummary;
  onOpenFilePreview?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const editing = edit.status === "editing";
  const failed = edit.status === "error";
  const hasCountedDiff = !failed && !edit.binary && hasVisibleDiffStats(edit);
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
      contentClassName={failed ? "min-w-0" : "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3"}
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
