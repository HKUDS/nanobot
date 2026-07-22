import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
} from "lucide-react";
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
    <>
      {edits.map((edit) => (
        <FileEditRow
          key={edit.key}
          edit={edit}
          onOpenFilePreview={onOpenFilePreview}
        />
      ))}
    </>
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
  const action = fileEditAction(edit, editing, failed);
  const hasCountedDiff = !failed && !edit.binary && hasVisibleDiffStats(edit);
  const statusIcon = failed ? (
    <AlertCircle className="h-3 w-3" aria-hidden />
  ) : editing ? (
    <CircleDashed className="h-3 w-3 animate-spin" aria-hidden />
  ) : (
    <CheckCircle2 className="h-3 w-3" aria-hidden />
  );

  return (
    <ActivityStep
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
      ariaLabel={edit.path ? `${action} ${edit.path}` : action}
      label={edit.pending && !edit.path
        ? t("message.fileEditPreparing", { defaultValue: "Preparing file edit…" })
        : (
          <span className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap">
            <span className="shrink-0">{action}</span>
            <FileReferenceChip
              path={edit.path}
              previewPath={edit.absolute_path || edit.path}
              onOpen={onOpenFilePreview}
              display="path"
              active={editing}
              className="min-w-0"
              textClassName="truncate text-[12px]"
              testId="activity-file-reference"
            />
            {hasCountedDiff ? <DiffPair added={edit.added} deleted={edit.deleted} /> : null}
          </span>
        )}
    />
  );
}

export function hasVisibleDiffStats(edit: Pick<FileEditSummary, "added" | "deleted">): boolean {
  return edit.added > 0 || edit.deleted > 0;
}

function fileEditAction(edit: FileEditSummary, editing: boolean, failed: boolean): string {
  const deleting = edit.operation === "delete";
  if (failed) return deleting ? "Could not delete" : "Could not edit";
  if (editing) return deleting ? "Deleting" : "Editing";
  return deleting ? "Deleted" : "Edited";
}
