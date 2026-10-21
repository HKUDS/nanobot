import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Copy, Maximize2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CodeBlock } from "@/components/CodeBlock";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { HoverHint } from "@/components/ui/hover-hint";
import { ImageViewport } from "@/components/ui/image-viewport";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { useDiagramScope } from "./context";
import { requestDiagram, type DiagramPalette, type DiagramRequest, type DiagramState } from "./runtime";
import type { DiagramInput } from "./types";

function readPalette(element: HTMLElement): DiagramPalette {
  const style = getComputedStyle(element);
  const color = (token: string) => `hsl(${style.getPropertyValue(token).trim()})`;
  return {
    "--pele-bg": color("--background"), "--pele-fg": color("--foreground"),
    "--pele-muted": color("--muted-foreground"), "--pele-line": color("--foreground"),
    "--pele-surface": color("--muted"), "--pele-surface-alt": color("--secondary"),
    "--pele-border": color("--border"), "--pele-accent": color("--primary"),
    "--pele-critical": color("--destructive"),
  };
}

export default function MermaidBlock({ source }: { source: string }) {
  const { t } = useTranslation();
  const scope = useDiagramScope();
  const container = useRef<HTMLDivElement>(null);
  const mono = useRef<HTMLSpanElement>(null);
  const request = useRef<DiagramRequest | null>(null);
  const palette = useRef<DiagramPalette>({});
  const visible = useRef(false);
  const height = useRef(0);
  const [input, setInput] = useState<Omit<DiagramInput, "source"> | null>(null);
  const [state, setState] = useState<DiagramState>({ kind: "waiting" });
  const [view, setView] = useState<"diagram" | "source">("diagram");
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  const demand = useRef({ view, open });
  demand.current = { view, open };

  const updateDemand = useCallback(() => request.current?.setDemand(document.hidden || demand.current.view === "source"
    ? "none" : demand.current.open ? "dialog" : visible.current ? "visible" : "none"), []);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let active = true;
    let frame = 0;
    const measure = () => {
      if (!active) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const width = Math.floor(element.clientWidth);
        if (width <= 0) return;
        const style = getComputedStyle(element);
        const next = { width, fonts: { sans: style.fontFamily, mono: getComputedStyle(mono.current!).fontFamily, size: 16 } };
        // The open viewer fits its existing image; defer layout changes until it closes.
        if (!demand.current.open) setInput((previous) => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
        palette.current = readPalette(element);
        request.current?.setPalette(palette.current);
      });
    };
    const resize = new ResizeObserver(measure);
    resize.observe(element);
    const intersection = new IntersectionObserver(([entry]) => {
      visible.current = entry.isIntersecting;
      updateDemand();
    });
    intersection.observe(element);
    const appearance = new MutationObserver(measure);
    appearance.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    document.addEventListener("visibilitychange", updateDemand);
    void document.fonts.ready.then(measure);
    measure();
    return () => {
      active = false;
      resize.disconnect(); intersection.disconnect(); appearance.disconnect();
      document.removeEventListener("visibilitychange", updateDemand);
      cancelAnimationFrame(frame);
    };
  }, [updateDemand, open]);

  useLayoutEffect(() => { setOpen(false); }, [source, scope]);
  useLayoutEffect(() => {
    setState({ kind: "waiting" });
    if (!input) return;
    const controller = new AbortController();
    const handle = requestDiagram({ ...input, source }, controller.signal, (next) => {
      if (controller.signal.aborted) return;
      if (next.kind === "ready") height.current = Math.min(448, next.image.height * Math.min(1, input.width / next.image.width));
      setState(next);
    });
    request.current = handle;
    handle.setPalette(palette.current);
    updateDemand();
    return () => { controller.abort(); request.current = null; };
  }, [source, scope, input, updateDemand]);

  useEffect(() => { updateDemand(); }, [view, open, updateDemand]);
  useEffect(() => () => clearTimeout(copyTimer.current), []);

  const copy = async () => {
    if (!await copyTextToClipboard(source)) return;
    setCopied(true);
    clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  };
  const buttonClass = "rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  const showSource = view === "source" || state.kind === "failed";
  const image = state.kind === "ready" ? state.image : null;

  return <div ref={container} className="not-prose my-3 min-w-0 overflow-hidden rounded-lg border border-border/60" data-testid="mermaid-block">
    <span ref={mono} className="hidden font-mono" aria-hidden />
    <div className="flex flex-wrap items-center gap-1 border-b border-border/60 px-2 py-1">
      <span className="mr-auto px-1 text-xs text-muted-foreground">Mermaid</span>
      <button type="button" aria-pressed={view === "diagram"} className={cn(buttonClass, view === "diagram" && "bg-muted text-foreground")} onClick={() => setView("diagram")}>{t("diagram.graph")}</button>
      <button type="button" aria-pressed={view === "source"} className={cn(buttonClass, view === "source" && "bg-muted text-foreground")} onClick={() => setView("source")}>{t("diagram.source")}</button>
      <HoverHint content={t("diagram.copy")}>
        <button type="button" className={buttonClass} aria-label={t("diagram.copy")} onClick={() => void copy()}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </HoverHint>
      <Dialog open={open && !!image} onOpenChange={setOpen}>
        <HoverHint content={t("diagram.enlarge")}>
          <DialogTrigger asChild><button type="button" className={buttonClass} aria-label={t("diagram.enlarge")} disabled={!image}><Maximize2 className="h-3.5 w-3.5" /></button></DialogTrigger>
        </HoverHint>
        <DialogContent className="h-[85dvh] max-w-[min(96vw,90rem)] gap-0 overflow-hidden p-3 sm:p-4" aria-describedby={undefined}>
          <DialogTitle className="sr-only">{t("diagram.title")}</DialogTitle>
          {image && <div className="flex h-full min-h-0 flex-col gap-2 pt-6"><ImageViewport src={image.url} alt={image.label || t("diagram.title")} className="flex-1" /></div>}
        </DialogContent>
      </Dialog>
    </div>
    {state.kind === "failed" && <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground" role="status">
      <span>{t(`diagram.errors.${state.reason}`)}</span>
      {["load", "worker", "deadline", "image"].includes(state.reason) && <button type="button" className={buttonClass} onClick={() => request.current?.retry()}>{t("common.retry")}</button>}
    </div>}
    {showSource ? <CodeBlock language="mermaid" code={source} chrome="none" highlight={false} showLineNumbers={source.includes("\n")} />
      : image ? <div className="flex justify-center p-3"><img src={image.url} alt={image.label || t("diagram.title")} width={image.width} height={image.height} className="max-h-[28rem] max-w-full object-contain" /></div>
      : <div className="px-3 py-2" style={{ minHeight: height.current || undefined }}>
        <p className="m-0 py-1 text-xs text-muted-foreground" role="status">{t("diagram.preparing")}</p>
        {!height.current && <CodeBlock language="mermaid" code={source} chrome="none" highlight={false} />}
      </div>}
  </div>;
}
