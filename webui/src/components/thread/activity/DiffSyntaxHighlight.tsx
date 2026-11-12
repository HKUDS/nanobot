import { Suspense, lazy, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { RenderableFileDiff, RenderableFileDiffLine } from "@/lib/file-diff";
import { cn } from "@/lib/utils";

export interface DiffSyntaxHighlightProps {
  language: string;
  text: string;
  diff: RenderableFileDiff;
  lineLimit: number;
}

const LazyDiffSyntaxHighlight = lazy(async () => {
  const renderer = await import("./PierreFileDiff");
  await renderer.prepareDiffRenderer();
  return { default: renderer.PierreFileDiff };
});

export function DiffSyntaxHighlight(props: DiffSyntaxHighlightProps) {
  return (
    <Suspense fallback={<PlainDiffLines diff={props.diff} lineLimit={props.lineLimit} />}>
      <LazyDiffSyntaxHighlight {...props} />
    </Suspense>
  );
}

export function DiffHunkGap({ lineCount }: { lineCount: number }) {
  const { t } = useTranslation();
  return (
    <div className="nanobot-diff-gap flex items-center gap-2 bg-muted/35 px-2 text-[11px] text-muted-foreground" data-testid="file-edit-diff-hunk-gap">
      <span className="select-none rounded border border-border/45 bg-background/70 px-1 font-mono text-muted-foreground/70" aria-hidden>...</span>
      <span>{t("message.fileEditUnchangedLinesHidden", { count: lineCount, defaultValue: "{{count}} unchanged lines hidden" })}</span>
    </div>
  );
}

export function PlainDiffLines({ diff, lineLimit }: { diff: RenderableFileDiff; lineLimit: number }) {
  let remaining = lineLimit;
  return <div data-testid="plain-diff-hunk">{diff.hunks.map((hunk, index) => {
    const lines = hunk.lines.slice(0, Math.max(0, remaining));
    remaining -= lines.length;
    if (lines.length === 0) return null;
    const previous = diff.hunks[index - 1];
    const skipped = previous ? Math.max(0, hunk.old_start - previous.old_start - previous.old_lines, hunk.new_start - previous.new_start - previous.new_lines) : 0;
    return <div key={index}>
      {skipped > 0 ? <DiffHunkGap lineCount={skipped} /> : null}
      <table className="w-full border-collapse font-mono text-code-dense"><tbody>
        {lines.map((line, lineIndex) => <DiffLineRow key={lineIndex} line={line}>{line.content || " "}</DiffLineRow>)}
      </tbody></table>
    </div>;
  })}</div>;
}

function DiffLineRow({ line, children }: { line: RenderableFileDiffLine; children: ReactNode }) {
  const kind = line.kind === "add" || line.kind === "delete" ? line.kind : "context";
  const marker = kind === "add" ? "+" : kind === "delete" ? "-" : " ";
  return (
    <tr className={cn("border-0", kind === "add" && "bg-diff-added", kind === "delete" && "bg-diff-deleted")}>
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground">{line.old_lineno ?? ""}</td>
      <td className="w-10 select-none border-r border-border/35 px-1.5 text-right text-muted-foreground">{line.new_lineno ?? ""}</td>
      <td className={cn("w-5 select-none px-1 text-center", kind === "add" && "text-diff-added-foreground", kind === "delete" && "text-diff-deleted-foreground", kind === "context" && "text-muted-foreground")}>{marker}</td>
      <td className="min-w-[16rem] px-1.5 text-foreground/86"><span className="whitespace-pre">{children}</span></td>
    </tr>
  );
}
