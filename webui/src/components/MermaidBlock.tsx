import { useEffect, useRef, useState, type PointerEvent } from "react";
import { Expand, Minus, Plus, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CodeBlock } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useThemeValue } from "@/hooks/useTheme";

type Diagram = { source: string; dark: boolean; url: string | null };

export function MermaidBlock({ code, streaming = false }: { code: string; streaming?: boolean }) {
  const { t } = useTranslation();
  const dark = useThemeValue() === "dark";
  const [diagram, setDiagram] = useState<Diagram | null>(null);
  const [showSource, setShowSource] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);

  useEffect(() => {
    if (streaming) return;
    const controller = new AbortController();
    let cancelled = false;
    let url: string | undefined;
    void import("@/lib/mermaid-renderer")
      .then(({ renderMermaid }) => renderMermaid(code, dark, controller.signal))
      .then((svg) => {
        if (cancelled) return;
        url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        setDiagram({ source: code, dark, url });
      })
      .catch(() => {
        if (!cancelled) setDiagram({ source: code, dark, url: null });
      });
    return () => {
      cancelled = true;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [code, dark, streaming]);

  const current = !streaming && diagram?.source === code && diagram.dark === dark ? diagram : null;
  const label = t("diagram.title");
  const sourceVisible = streaming || showSource || !current?.url;
  const onDragStart = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || event.pointerType === "touch") return;
    const node = event.currentTarget;
    node.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, left: node.scrollLeft, top: node.scrollTop };
  };
  const onDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    event.currentTarget.scrollLeft = drag.current.left - event.clientX + drag.current.x;
    event.currentTarget.scrollTop = drag.current.top - event.clientY + drag.current.y;
  };

  return (
    <section className="not-prose my-3 overflow-hidden rounded-floating border border-border/65 bg-secondary/30" aria-label={label}>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <span className="text-xs text-muted-foreground">{label}</span>
        <div className="flex items-center gap-1">
          {current?.url ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => setShowSource(!showSource)}>
                {showSource ? t("diagram.showDiagram") : t("diagram.showSource")}
              </Button>
              <Button variant="ghost" size="icon" aria-label={t("diagram.expand")} onClick={() => { setZoom(1); setExpanded(true); }}>
                <Expand className="h-4 w-4" />
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {sourceVisible ? (
        <>
          {!streaming && current && !current.url ? <p role="status" className="px-3 text-xs text-muted-foreground">{t("diagram.unavailable")}</p> : null}
          <CodeBlock language="mermaid" code={code} highlight={false} />
        </>
      ) : (
        <img src={current!.url!} alt={label} className="mx-auto max-h-[28rem] max-w-full p-4"
          onError={() => setDiagram({ source: code, dark, url: null })} />
      )}
      <Dialog open={expanded && Boolean(current?.url)} onOpenChange={setExpanded}>
        <DialogContent className="max-w-5xl" aria-describedby={undefined}>
          <DialogTitle>{label}</DialogTitle>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" aria-label={t("diagram.zoomOut")} disabled={zoom <= 0.5} onClick={() => setZoom((v) => Math.max(0.5, v - 0.25))}><Minus className="h-4 w-4" /></Button>
            <span className="w-12 text-center text-xs tabular-nums" aria-live="polite">{Math.round(zoom * 100)}%</span>
            <Button variant="ghost" size="icon" aria-label={t("diagram.zoomIn")} disabled={zoom >= 3} onClick={() => setZoom((v) => Math.min(3, v + 0.25))}><Plus className="h-4 w-4" /></Button>
            <Button variant="ghost" size="icon" aria-label={t("diagram.resetZoom")} onClick={() => setZoom(1)}><RotateCcw className="h-4 w-4" /></Button>
          </div>
          <div className="h-[65dvh] overflow-auto overscroll-contain rounded-panel bg-secondary/30 cursor-grab active:cursor-grabbing"
            tabIndex={0} role="region" aria-label={t("diagram.pan")}
            onPointerDown={onDragStart} onPointerMove={onDrag}
            onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
            {current?.url ? <img src={current.url} alt={label} draggable={false} style={{ width: `${zoom * 100}%`, maxWidth: "none" }} className="p-4" /> : null}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
