import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { CodeLine } from "@/lib/code-tokens";
import { CodeTokens } from "./CodeTokens";
const CHUNK_LINES = 40;

const CodeChunk = memo(function CodeChunk({ lines, text, start, highlighted }: {
  lines: CodeLine[];
  text: string;
  start: number;
  highlighted: boolean;
}) {
  return (
    <span data-code-chunk={start / CHUNK_LINES} className="flex min-w-max">
      <span aria-hidden className="shrink-0 select-none pr-[1.15rem] text-right text-muted-foreground"
        style={{ minWidth: "4.25em" }}>
        {lines.map((_, index) => start + index + 1).join("\n")}
      </span>
      <span data-highlighted={highlighted}>
        {highlighted ? <CodeTokens lines={lines} /> : text}
      </span>
    </span>
  );
});

/** Keep the complete source searchable/selectable; only offscreen token spans are omitted. */
export function ViewportCodeRows({ lines }: { lines: CodeLine[] }) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(() => new Set([0]));
  const chunks = useMemo(() => {
    const result = [];
    for (let start = 0; start < lines.length; start += CHUNK_LINES) {
      const chunk = lines.slice(start, start + CHUNK_LINES);
      result.push({ start, lines: chunk, text: chunk.map(line => line.text).join("") });
    }
    return result;
  }, [lines]);

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
      {chunks.map((chunk, index) => <CodeChunk key={chunk.start} {...chunk} highlighted={visible.has(index)} />)}
    </span>
  );
}
