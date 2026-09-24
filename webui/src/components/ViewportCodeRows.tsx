import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";
import createElement from "react-syntax-highlighter/dist/esm/create-element";

type RowsProps = Parameters<NonNullable<SyntaxHighlighterProps["renderer"]>>[0];
type Row = RowsProps["rows"][number];
const CHUNK_LINES = 40;

function textOf(node: Row): string {
  return node.type === "text" ? String(node.value ?? "") : (node.children ?? []).map(textOf).join("");
}

const CodeChunk = memo(function CodeChunk({ rows, text, start, stylesheet, useInlineStyles, highlighted }: RowsProps & {
  text: string;
  start: number;
  highlighted: boolean;
}) {
  return (
    <span data-code-chunk={start / CHUNK_LINES} className="flex min-w-max">
      <span aria-hidden className="shrink-0 select-none pr-[1.15rem] text-right text-muted-foreground/60"
        style={{ minWidth: "4.25em" }}>
        {rows.map((_, index) => start + index + 1).join("\n")}
      </span>
      <span data-highlighted={highlighted}>
        {highlighted ? rows.map((node, index) => createElement({
          node, stylesheet, useInlineStyles, key: start + index,
        })) : text}
      </span>
    </span>
  );
});

/** Keep the complete source searchable/selectable; only offscreen token spans are omitted. */
export function ViewportCodeRows({ rows, stylesheet, useInlineStyles }: RowsProps) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(() => new Set([0]));
  // The inline renderer only matches token class combinations. Passing Prism's
  // unrelated toolbar/pseudo selectors makes it scan those again for every token.
  const tokenStyles = useMemo(() => Object.fromEntries(Object.entries(stylesheet)
    .filter(([selector]) => /^[\w-]+(?:\.[\w-]+)*$/.test(selector))), [stylesheet]);
  const chunks = useMemo(() => {
    const result = [];
    for (let start = 0; start < rows.length; start += CHUNK_LINES) {
      const chunk = rows.slice(start, start + CHUNK_LINES);
      result.push({ start, rows: chunk, text: chunk.map(textOf).join("") });
    }
    return result;
  }, [rows]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const intersecting = new Set<number>();
    const update = () => {
      // Replacing spans during a drag/keyboard selection would destroy its Range.
      const selection = document.getSelection();
      if (selection && !selection.isCollapsed && selection.rangeCount
        && selection.getRangeAt(0).intersectsNode(root)) return;
      setVisible((previous) => previous.size === intersecting.size
        && [...previous].every(index => intersecting.has(index)) ? previous : new Set(intersecting));
    };
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const index = Number((entry.target as HTMLElement).dataset.codeChunk);
        if (entry.isIntersecting) intersecting.add(index);
        else intersecting.delete(index);
      }
      update();
    }, { root: root.closest("[data-file-preview-scroll]"), rootMargin: "80px 0px" });
    root.querySelectorAll("[data-code-chunk]").forEach(chunk => observer.observe(chunk));
    document.addEventListener("selectionchange", update);
    return () => {
      observer.disconnect();
      document.removeEventListener("selectionchange", update);
    };
  }, [chunks]);

  return (
    <span ref={rootRef} className="block min-w-max" data-testid="viewport-code-rows">
      {chunks.map((chunk, index) => <CodeChunk key={chunk.start} {...chunk}
        stylesheet={tokenStyles} useInlineStyles={useInlineStyles} highlighted={visible.has(index)} />)}
    </span>
  );
}
