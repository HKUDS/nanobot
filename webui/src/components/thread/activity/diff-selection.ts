import type { FileDiffMetadata } from "@pierre/diffs";

// Native ranges must be read inside Pierre's shadow tree, not from retargeted host endpoints.
export function selectedDiffRows(wrapper: HTMLElement, metadata: FileDiffMetadata): readonly [number, number] | undefined {
  const host = wrapper.querySelector("diffs-container");
  const root = host?.shadowRoot;
  const selection = document.getSelection();
  if (!root || !selection) return;
  const shadowSelection = (root as ShadowRoot & { getSelection?(): Selection | null }).getSelection?.();
  const ranges = typeof selection.getComposedRanges === "function"
    ? selection.getComposedRanges({ shadowRoots: [root] })
    : shadowSelection?.rangeCount ? [shadowSelection.getRangeAt(0)] : selection.rangeCount ? [selection.getRangeAt(0)] : [];
  const selected = ranges[0];
  // Chromium can report document Selection.isCollapsed=true for a nonempty shadow selection.
  if (!selected || (selected.startContainer === selected.endContainer && selected.startOffset === selected.endOffset)) return;
  const startsInside = selected.startContainer.getRootNode() === root;
  const endsInside = selected.endContainer.getRootNode() === root;
  if (!startsInside && !endsInside && (!selection.rangeCount || !selection.getRangeAt(0).intersectsNode(host))) return;
  const localRange = document.createRange();
  localRange.selectNodeContents(root);
  if (startsInside) localRange.setStart(selected.startContainer, selected.startOffset);
  if (endsInside) localRange.setEnd(selected.endContainer, selected.endOffset);
  let first: number | undefined;
  let last: number | undefined;
  for (const row of root.querySelectorAll<HTMLElement>("[data-code] [data-line][data-line-index]")) {
    if (!localRange.intersectsNode(row)) continue;
    const index = Number(row.dataset.lineIndex!.split(",")[0]);
    let renderedStart = 0;
    for (const hunk of metadata.hunks) {
      if (index >= hunk.unifiedLineStart && index < hunk.unifiedLineStart + hunk.unifiedLineCount) {
        const renderedIndex = renderedStart + index - hunk.unifiedLineStart;
        first = first === undefined ? renderedIndex : Math.min(first, renderedIndex);
        last = last === undefined ? renderedIndex + 1 : Math.max(last, renderedIndex + 1);
        break;
      }
      renderedStart += hunk.unifiedLineCount;
    }
  }
  return first === undefined || last === undefined ? undefined : [first, last];
}
