import { Check, Trash2, TriangleAlert } from "lucide-react";
import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import "./toast.css";

const TOAST_NOTICE_MS = 3_000;
export const TOAST_ACTION_MS = 8_000;

export type ToastNotice = {
  message: string;
  detail?: string;
  tone: "success" | "error" | "pending";
  dedupeKey?: string;
  action?: { label: string; run: () => void };
  onExpire?: () => void;
};

function toastDurationMs(notice: ToastNotice) {
  return notice.action ? TOAST_ACTION_MS : TOAST_NOTICE_MS;
}

type ToastEntry = ToastNotice & { id: number };
const ToastContext = createContext<((notice: ToastNotice) => void) | null>(null);
export const useToast = () => useContext(ToastContext);

export function ToastViewport({ children }: { children: ReactNode }) {
  return <div className="pointer-events-none fixed inset-x-3 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 mx-auto flex max-w-[22rem] flex-col items-center gap-2 [.native-host_&]:top-12">
    {children}
  </div>;
}

export function ToastCard({ notice, paused = false, onAction, onHoverChange, onFocusChange }: {
  notice: ToastNotice;
  paused?: boolean;
  onAction: () => void;
  onHoverChange?: (hovered: boolean) => void;
  onFocusChange?: (focused: boolean) => void;
}) {
  const { message, detail, tone, action } = notice;
  const Icon = tone === "error" ? TriangleAlert : tone === "pending" ? Trash2 : Check;
  return <div
    className={`toast-card isolate relative flex min-h-10 max-w-full items-center gap-2 px-3 py-0.5${action ? " pointer-events-auto" : ""}`}
    style={{
      "--toast-duration": `${toastDurationMs(notice)}ms`,
      "--toast-play-state": paused ? "paused" : "running",
    } as CSSProperties}
    onPointerEnter={(event) => { if (event.pointerType !== "touch") onHoverChange?.(true); }}
    onPointerLeave={() => onHoverChange?.(false)}
    onFocus={() => onFocusChange?.(true)}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) onFocusChange?.(false); }}
    data-toast-tone={tone}
  >
    <Icon aria-hidden="true" size={15} strokeWidth={2} className="shrink-0" />
    <div role={tone === "error" ? "alert" : "status"} className="min-w-0 truncate text-sm leading-5"
      title={detail ? `${message} ${detail}` : message}>
      <span className={detail ? "text-muted-foreground" : "font-medium"}>{message}</span>
      {detail && <> <span className="font-medium">{detail}</span></>}
    </div>
    {action && <Button type="button" variant="ghost" size="sm" onClick={onAction} className="h-8 shrink-0 px-2">{action.label}</Button>}
  </div>;
}

type ToastFinishReason = "action" | "expired";

function TimedToast({ entry, finish }: { entry: ToastEntry; finish: (entry: ToastEntry, reason: ToastFinishReason) => void }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  const remaining = useRef(toastDurationMs(entry));
  useLayoutEffect(() => {
    if (paused) return;
    const start = performance.now();
    const timer = window.setTimeout(() => finish(entry, "expired"), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(0, remaining.current - (performance.now() - start));
    };
  }, [entry, finish, paused]);

  return <ToastCard notice={entry} paused={paused} onAction={() => finish(entry, "action")}
    onHoverChange={entry.action ? setHovered : undefined} onFocusChange={entry.action ? setFocused : undefined} />;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<ToastEntry[]>([]);
  const nextId = useRef(0);
  const live = useRef(new Map<number, ToastEntry>());
  const publish = useCallback(() => setEntries([...live.current.values()]), []);
  const show = useCallback((notice: ToastNotice) => {
    if (notice.dedupeKey && !notice.action && !notice.onExpire) {
      for (const [id, entry] of live.current) {
        if (entry.dedupeKey === notice.dedupeKey && !entry.action && !entry.onExpire) live.current.delete(id);
      }
    }
    const entry = { ...notice, id: ++nextId.current };
    live.current.set(entry.id, entry);
    publish();
  }, [publish]);
  const finish = useCallback((entry: ToastEntry, reason: ToastFinishReason) => {
    if (!live.current.delete(entry.id)) return;
    publish();
    if (reason === "action") entry.action?.run();
    else entry.onExpire?.();
  }, [publish]);
  return <ToastContext.Provider value={show}>
    {children}
    <ToastViewport>{entries.map((entry) => <TimedToast key={entry.id} entry={entry} finish={finish} />)}</ToastViewport>
  </ToastContext.Provider>;
}
