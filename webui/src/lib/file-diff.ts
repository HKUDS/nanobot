import { parsePatch } from "diff";

import type { UIFileDiff } from "@/lib/types";

export interface RenderableFileDiffLine {
  kind: "context" | "add" | "delete";
  old_lineno?: number | null;
  new_lineno?: number | null;
  content: string;
}

export interface RenderableFileDiffHunk {
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  lines: RenderableFileDiffLine[];
}

export interface RenderableFileDiff {
  hunks: RenderableFileDiffHunk[];
}

export function hasRenderableFileDiff(diff?: UIFileDiff): boolean {
  if (!diff) return false;
  return typeof diff.text === "string" && diff.text.trim().length > 0;
}

export function parseRenderableFileDiff(diff: UIFileDiff): RenderableFileDiff {
  if (typeof diff.text === "string" && diff.text.trim().length > 0) {
    return parseUnifiedDiffText(diff.text);
  }
  return { hunks: [] };
}

function parseUnifiedDiffText(text: string): RenderableFileDiff {
  let files: ReturnType<typeof parsePatch>;
  try {
    files = parsePatch(text);
  } catch {
    return { hunks: [] };
  }
  return {
    hunks: files.flatMap((file) =>
      file.hunks.map((hunk) => {
        let oldLineno = hunk.oldStart;
        let newLineno = hunk.newStart;
        const lines: RenderableFileDiffLine[] = [];

        for (const rawLine of hunk.lines) {
          if (rawLine.startsWith("\\")) continue;
          const marker = rawLine[0];
          const content = rawLine.slice(1);
          if (marker === "+") {
            lines.push({
              kind: "add",
              old_lineno: null,
              new_lineno: newLineno,
              content,
            });
            newLineno += 1;
            continue;
          }
          if (marker === "-") {
            lines.push({
              kind: "delete",
              old_lineno: oldLineno,
              new_lineno: null,
              content,
            });
            oldLineno += 1;
            continue;
          }
          lines.push({
            kind: "context",
            old_lineno: oldLineno,
            new_lineno: newLineno,
            content: marker === " " ? content : rawLine,
          });
          oldLineno += 1;
          newLineno += 1;
        }

        return {
          old_start: hunk.oldStart,
          old_lines: hunk.oldLines,
          new_start: hunk.newStart,
          new_lines: hunk.newLines,
          lines,
        };
      }),
    ),
  };
}
