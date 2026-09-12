import { useLayoutEffect, useRef, useState } from "react";

/** Animate a line-limited preview without swapping or duplicating its text. */
export function ExpandableText({
  children, expanded, lines, className, id,
}: {
  children: string;
  expanded: boolean;
  lines: number;
  className?: string;
  id?: string;
}) {
  const content = useRef<HTMLParagraphElement>(null);
  const [size, setSize] = useState<{ full: number; preview: number }>();
  useLayoutEffect(() => {
    const node = content.current;
    if (!node) return;
    const measure = () => {
      const full = node.scrollHeight;
      const lineHeight = parseFloat(getComputedStyle(node).lineHeight);
      if (!full || !Number.isFinite(lineHeight)) return;
      const preview = Math.min(full, lineHeight * lines);
      setSize((current) => current?.full === full && current.preview === preview
        ? current : { full, preview });
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(node);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [children, lines, className]);

  return (
    <div
      id={id}
      className="expandable-text flow-root overflow-hidden"
      data-state={expanded ? "open" : "closed"}
      style={{ height: size ? expanded ? size.full : size.preview : undefined }}
    >
      <p ref={content} className={className}>{children}</p>
    </div>
  );
}
