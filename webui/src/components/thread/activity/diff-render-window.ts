import type { RenderableFileDiff } from "@/lib/file-diff";

export const DIFF_GAP_HEIGHT = 26;
const ROW_BATCH = 40;

export function diffRowOffsets(diff: RenderableFileDiff, lineLimit: number, lineHeight: number): number[] {
  const offsets: number[] = [];
  let top = 0;
  for (const [index, hunk] of diff.hunks.entries()) {
    if (offsets.length >= lineLimit) break;
    const previous = diff.hunks[index - 1];
    if (previous && (hunk.old_start > previous.old_start + previous.old_lines || hunk.new_start > previous.new_start + previous.new_lines)) top += DIFF_GAP_HEIGHT;
    for (let line = 0; line < hunk.lines.length; line++) {
      if (offsets.length >= lineLimit) break;
      offsets.push(top);
      top += lineHeight;
    }
  }
  offsets.push(top);
  return offsets;
}

export function diffRenderWindow(diff: RenderableFileDiff, offsets: number[], top: number, bottom: number, lineHeight: number, selected?: readonly [number, number]) {
  const count = offsets.length - 1;
  if (count <= 160) return { startingLine: 0, totalLines: count, bufferBefore: 0, bufferAfter: 0 };
  let start = offsets.findIndex((offset) => offset >= top);
  if (start < 0) start = count - 1;
  // Keep both edges together, with one extra batch for the rounded-down start.
  const capacity = Math.min(count, (Math.ceil((bottom - top) / lineHeight / ROW_BATCH) + 1) * ROW_BATCH);
  start = Math.min(count - capacity, Math.max(0, Math.floor((start - 1) / ROW_BATCH) * ROW_BATCH));
  let end = start + capacity;
  // Retain only the active selection's rows as the viewport keeps moving. Clearing it
  // returns to the ordinary bounded window; do not freeze rendering or accumulate old windows.
  if (selected) {
    start = Math.min(start, selected[0]);
    end = Math.min(count, Math.max(end, selected[1]));
  }
  let before = offsets[start];
  let after = offsets[count] - offsets[end];
  // A separator is rendered with its first row, not with the preceding window.
  let row = 0;
  for (const [index, hunk] of diff.hunks.entries()) {
    const previous = diff.hunks[index - 1];
    const gap = previous && (hunk.old_start > previous.old_start + previous.old_lines || hunk.new_start > previous.new_start + previous.new_lines);
    if (gap && row === start) before -= DIFF_GAP_HEIGHT;
    if (gap && row === end) after += DIFF_GAP_HEIGHT;
    row += hunk.lines.length;
  }
  return { startingLine: start, totalLines: end - start, bufferBefore: before, bufferAfter: after };
}
