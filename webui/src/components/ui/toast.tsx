import { Check, Trash2, TriangleAlert } from "lucide-react";
import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref } from "react";

import { Button } from "@/components/ui/button";
import "./toast.css";

const TOAST_NOTICE_MS = 3_000;
export const TOAST_ACTION_MS = 8_000;

type ToastAction = {
  label: string;
  run: () => void | ToastNotice;
  tone?: "default" | "destructive";
};

export type ToastNotice = {
  message: string;
  detail?: string;
  tone: "success" | "error" | "pending";
  dedupeKey?: string;
  persistent?: boolean;
  action?: ToastAction;
  secondaryAction?: { label: string; run?: () => void };
  onExpire?: () => void;
};

function toastDurationMs(notice: ToastNotice) {
  return notice.action ? TOAST_ACTION_MS : TOAST_NOTICE_MS;
}

type ToastEntry = ToastNotice & { id: number; step: number };
const ToastContext = createContext<((notice: ToastNotice) => void) | null>(null);
export const useToast = () => useContext(ToastContext);

function ToastViewport({ children, viewportRef, hidden }: { children: ReactNode; viewportRef: Ref<HTMLDivElement>; hidden: boolean }) {
  return <div ref={viewportRef} className="pointer-events-none fixed inset-x-3 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 mx-auto flex max-w-[min(calc(100vw-1.5rem),28rem)] flex-col items-center gap-2 [.native-host_&]:top-12" style={hidden ? { visibility: "hidden" } : undefined}>
    {children}
  </div>;
}

function ToastCard({ notice, step, paused, onAction, onSecondaryAction, onHoverChange, onFocusChange }: {
  notice: ToastNotice;
  step: number;
  paused: boolean;
  onAction: () => void;
  onSecondaryAction: () => void;
  onHoverChange?: (hovered: boolean) => void;
  onFocusChange?: (focused: boolean) => void;
}) {
  const { message, detail, tone, persistent, action, secondaryAction } = notice;
  const Icon = tone === "error" ? TriangleAlert : tone === "pending" ? Trash2 : Check;
  const interactive = Boolean(action || secondaryAction);
  const stacked = Boolean(persistent && detail);
  return <div
    className={`toast-card isolate relative flex min-h-10 max-w-full items-center gap-2 ${stacked ? "px-3.5 py-1.5" : "px-3 py-0.5"}${interactive ? " pointer-events-auto" : ""}`}
    style={{
      "--toast-duration": `${toastDurationMs(notice)}ms`,
      "--toast-play-state": paused ? "paused" : "running",
    } as CSSProperties}
    onPointerEnter={(event) => { if (event.pointerType !== "touch") onHoverChange?.(true); }}
    onPointerLeave={() => onHoverChange?.(false)}
    onFocus={() => onFocusChange?.(true)}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) onFocusChange?.(false); }}
    data-toast-tone={tone}
    data-toast-timed={persistent ? "false" : "true"}
  >
    <Icon aria-hidden="true" size={15} strokeWidth={2} className="shrink-0" />
    <div role={tone === "error" ? "alert" : "status"} className={stacked ? "flex min-w-0 flex-col text-sm leading-5" : "min-w-0 truncate text-sm leading-5"}
      title={detail ? `${message} ${detail}` : message}>
      {stacked ? (
        <>
          <span className="truncate font-medium">{message}</span>
          <span className="truncate text-xs text-muted-foreground">{detail}</span>
        </>
      ) : (
        <>
          <span className={detail ? "text-muted-foreground" : "font-medium"}>{message}</span>
          {detail && <> <span className="font-medium">{detail}</span></>}
        </>
      )}
    </div>
    {secondaryAction && (
      <Button
        key={`secondary-${step}`}
        type="button"
        variant="ghost"
        size="sm"
        onClick={onSecondaryAction}
        className="h-8 shrink-0 px-2 text-muted-foreground hover:text-foreground"
      >
        {secondaryAction.label}
      </Button>
    )}
    {action && (
      <Button
        key={`action-${step}`}
        type="button"
        variant="ghost"
        size="sm"
        onClick={onAction}
        className={action.tone === "destructive"
          ? "h-8 shrink-0 px-2 font-medium text-destructive hover:bg-destructive/10 hover:text-destructive"
          : "h-8 shrink-0 px-2"}
      >
        {action.label}
      </Button>
    )}
  </div>;
}

type ToastFinishReason = "action" | "secondary" | "expired";

function TimedToast({ entry, finish, unavailable }: {
  entry: ToastEntry;
  finish: (entry: ToastEntry, reason: ToastFinishReason) => void;
  unavailable: boolean;
}) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const persistent = Boolean(entry.persistent);
  const paused = persistent || unavailable || hovered || focused;
  const remaining = useRef(toastDurationMs(entry));
  useLayoutEffect(() => {
    setHovered(false);
    setFocused(false);
    remaining.current = toastDurationMs(entry);
  }, [entry.step]);
  useLayoutEffect(() => {
    if (!unavailable) return;
    setHovered(false);
    setFocused(false);
  }, [unavailable]);
  useLayoutEffect(() => {
    if (paused) return;
    const start = performance.now();
    const timer = window.setTimeout(() => finish(entry, "expired"), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(0, remaining.current - (performance.now() - start));
    };
  }, [entry, finish, paused]);

  return <ToastCard notice={entry} step={entry.step} paused={paused}
    onAction={() => finish(entry, "action")}
    onSecondaryAction={() => finish(entry, "secondary")}
    onHoverChange={!persistent && entry.action ? setHovered : undefined}
    onFocusChange={!persistent && entry.action ? setFocused : undefined} />;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<ToastEntry[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const visibilityTree: HTMLElement[] = [];
    for (let node: HTMLElement | null = viewportRef.current; node; node = node.parentElement) visibilityTree.push(node);
    // Radix dialogs/sheets hide the surrounding tree; inactive remote hosts are inert.
    const update = () => setUnavailable(document.visibilityState === "hidden" || visibilityTree.some((node) => (
      node.getAttribute("aria-hidden") === "true" || node.hasAttribute("inert")
    )));
    const observer = new MutationObserver(update);
    for (const node of visibilityTree) observer.observe(node, { attributeFilter: ["aria-hidden", "inert"] });
    document.addEventListener("visibilitychange", update);
    update();
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  const nextId = useRef(0);
  const live = useRef(new Map<number, ToastEntry>());
  const publish = useCallback(() => setEntries([...live.current.values()]), []);
  const show = useCallback((notice: ToastNotice) => {
    if (notice.dedupeKey && !notice.onExpire && (!notice.action || notice.persistent)) {
      for (const [id, entry] of live.current) {
        if (entry.dedupeKey === notice.dedupeKey && !entry.onExpire && (!entry.action || entry.persistent)) {
          live.current.delete(id);
        }
      }
    }
    const entry = { ...notice, id: ++nextId.current, step: 0 };
    live.current.set(entry.id, entry);
    publish();
  }, [publish]);
  const finish = useCallback((entry: ToastEntry, reason: ToastFinishReason) => {
    const current = live.current.get(entry.id);
    if (!current || current.step !== entry.step) return;
    if (reason === "action") {
      const next = current.action?.run();
      if (next) {
        live.current.set(entry.id, { ...next, id: entry.id, step: current.step + 1 });
        publish();
        return;
      }
    }
    live.current.delete(entry.id);
    publish();
    if (reason === "secondary") current.secondaryAction?.run?.();
    else if (reason === "expired") current.onExpire?.();
  }, [publish]);
  return <ToastContext.Provider value={show}>
    {children}
    <ToastViewport viewportRef={viewportRef} hidden={unavailable}>
      {entries.map((entry) => <TimedToast key={entry.id} entry={entry} finish={finish} unavailable={unavailable} />)}
    </ToastViewport>
  </ToastContext.Provider>;
}
