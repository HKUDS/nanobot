import type { Nodes } from "mdast";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import { parseMarkdownIntoBlocks } from "streamdown";
import { unified } from "unified";

import { remarkTexMath } from "@/lib/remark-tex-math";

const boundaryParser = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath, { singleDollarTextMath: false })
  .use(remarkTexMath, { allowUnclosedFlow: true })
  .freeze();

function containsMath(node: Nodes): boolean {
  return node.type === "math" || node.type === "inlineMath"
    || ("children" in node && node.children.some(containsMath));
}

/** Keep formula boundaries intact without replacing Streamdown's ordinary block grouping. */
export function parseMathAwareMarkdownBlocks(source: string): string[] {
  const blocks = parseMarkdownIntoBlocks(source);
  if (blocks.length < 2 || !/\$\$|\\\[/.test(source)) return blocks;

  // Marked normalizes line endings. Do not compare its offsets against different source bytes.
  if (blocks.join("") !== source) return [source];

  const ranges: Array<{ start: number; end: number }> = [];
  for (const node of boundaryParser.parse(source).children) {
    if (!containsMath(node)) continue;
    const start = node.position?.start.offset;
    const end = node.position?.end.offset;
    if (start === undefined || end === undefined) return [source];
    // Protect the enclosing list/quote too: isolated continuation lines lose their container.
    ranges.push({ start, end });
  }
  if (ranges.length === 0) return blocks;

  const merged: string[] = [];
  let pending = "";
  let offset = 0;
  let rangeIndex = 0;
  for (const block of blocks) {
    pending += block;
    offset += block.length;
    while (rangeIndex < ranges.length && offset >= ranges[rangeIndex].end) rangeIndex++;
    const range = ranges[rangeIndex];
    if (range && range.start < offset && offset < range.end) continue;
    merged.push(pending);
    pending = "";
  }
  if (pending) merged.push(pending);
  return merged;
}
