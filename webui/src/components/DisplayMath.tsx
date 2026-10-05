import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export function DisplayMath({ children }: { children: ReactNode }) {
  const frame = useRef<HTMLSpanElement>(null);
  const content = useRef<HTMLSpanElement>(null);
  const [layout, setLayout] = useState({ scale: 1, height: 0 });
  useLayoutEffect(() => {
    const update = () => {
      if (!frame.current || !content.current) return;
      const width = content.current.offsetWidth;
      const scale = width ? Math.min(1, frame.current.clientWidth / width) : 1;
      const height = content.current.offsetHeight * scale;
      setLayout(previous => previous.scale === scale && previous.height === height ? previous : { scale, height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(frame.current!);
    observer.observe(content.current!);
    let cancelled = false;
    void document.fonts?.ready.then(() => { if (!cancelled) update(); });
    return () => { cancelled = true; observer.disconnect(); };
  }, [children]);
  return <span ref={frame} className="math-fit" style={{ height: layout.height || undefined }}
    data-math-scale={layout.scale}>
    <span ref={content} className="math-fit-content" style={{ transform: `translateX(var(--math-translate, -50%)) scale(${layout.scale})` }}>
      <span className="katex-display">{children}</span>
    </span>
  </span>;
}
