import { useEffect, useState } from "react";
import { AlertTriangle, Clock, Columns2, Pin } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HoverHint } from "@/components/ui/hover-hint";
import {
  formatElapsedDuration,
  type SessionAttentionState,
} from "@/lib/session-intelligence";
import type { SessionHandle } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Shared 1-second ticker only mounted when at least one running session is visible. */
export function useLiveClock(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs]);
  return now;
}

export function SessionStatusDot({
  state,
  size = "sm",
  className,
}: {
  state: SessionAttentionState;
  size?: "sm" | "md";
  className?: string;
}) {
  const { t } = useTranslation();

  if (state === "recovery") {
    const label = t("chat.activity.recovery", {
      defaultValue: "Needs your attention",
    });
    return (
      <HoverHint content={label} side="top">
        <span
          role="img"
          aria-label={label}
          className={cn(
            "inline-flex shrink-0 items-center justify-center text-amber-500 dark:text-amber-400",
            size === "md" ? "h-4 w-4" : "h-3.5 w-3.5",
            className,
          )}
        >
          <AlertTriangle className={size === "md" ? "h-4 w-4" : "h-3.5 w-3.5"} strokeWidth={2.1} aria-hidden />
        </span>
      </HoverHint>
    );
  }

  if (state === "running") {
    const label = t("chat.activity.running", { defaultValue: "Running" });
    return (
      <HoverHint content={label} side="top">
        <span
          role="img"
          aria-label={label}
          className={cn(
            "relative inline-flex shrink-0 items-center justify-center",
            size === "md" ? "h-4 w-4" : "h-3.5 w-3.5",
            className,
          )}
        >
          <span
            aria-hidden
            className={cn(
              "absolute rounded-full bg-emerald-500/35 motion-safe:animate-ping",
              size === "md" ? "h-3 w-3" : "h-2.5 w-2.5",
            )}
          />
          <span
            aria-hidden
            className={cn(
              "relative rounded-full bg-emerald-500 shadow-[0_0_0_2px_rgba(16,185,129,0.18)]",
              size === "md" ? "h-2 w-2" : "h-[7px] w-[7px]",
            )}
          />
        </span>
      </HoverHint>
    );
  }

  if (state === "updated") {
    const label = t("chat.activity.updated", { defaultValue: "New update" });
    return (
      <HoverHint content={label} side="top">
        <span
          role="img"
          aria-label={label}
          className={cn(
            "inline-flex shrink-0 items-center justify-center",
            size === "md" ? "h-4 w-4" : "h-3.5 w-3.5",
            className,
          )}
        >
          <span
            aria-hidden
            className={cn(
              "rounded-full bg-[#ff8a3d] shadow-[0_0_0_2px_rgba(255,138,61,0.18)]",
              size === "md" ? "h-2 w-2" : "h-[7px] w-[7px]",
            )}
          />
        </span>
      </HoverHint>
    );
  }

  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center",
        size === "md" ? "h-4 w-4" : "h-3.5 w-3.5",
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30" />
    </span>
  );
}

export function LiveElapsedBadge({
  startedAtSec,
  nowMs,
  className,
}: {
  startedAtSec: number | null | undefined;
  nowMs: number;
  className?: string;
}) {
  const elapsed = formatElapsedDuration(startedAtSec, nowMs);
  if (!elapsed) return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] font-medium tabular-nums text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
        className,
      )}
    >
      {elapsed}
    </span>
  );
}

export function ProjectDot({
  color,
  className,
}: {
  color: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-2 w-2 shrink-0 rounded-full opacity-85", className)}
      style={{ backgroundColor: color }}
    />
  );
}

/**
 * De-noised @handle presentation: subtle neutral monospace token without loud colored underlines,
 * reserving saturated colors strictly for actionable session states.
 */
export function MutedHandleBadge({
  handle,
  className,
}: {
  handle: SessionHandle | null | undefined;
  className?: string;
}) {
  if (!handle) return null;
  return (
    <span
      className={cn(
        "inline-flex max-w-28 shrink-0 items-center truncate rounded-md bg-muted/80 px-1.5 py-0.5 font-mono text-[10.5px] font-medium leading-none text-muted-foreground",
        className,
      )}
    >
      @{handle.name}
    </span>
  );
}

export function AutomationProtectedBadge({
  count,
  compact = false,
}: {
  count: number;
  compact?: boolean;
}) {
  const { i18n } = useTranslation();
  if (count <= 0) return null;
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const label = isZh
    ? `绑定了 ${count} 个定时任务`
    : `${count} linked automation${count > 1 ? "s" : ""}`;
  return (
    <HoverHint content={label} side="top">
      <span
        aria-label={label}
        className="inline-flex shrink-0 items-center gap-1 rounded-md bg-muted/70 px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground"
      >
        <Clock className="h-3 w-3 shrink-0" aria-hidden />
        {!compact && <span className="tabular-nums">{count}</span>}
      </span>
    </HoverHint>
  );
}

export function SplitGroupBadge({
  title,
  compact = false,
}: {
  title: string | null;
  compact?: boolean;
}) {
  const { i18n } = useTranslation();
  if (!title) return null;
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const label = isZh ? `分屏组：${title}` : `Split group: ${title}`;
  return (
    <HoverHint content={label} side="top">
      <span
        aria-label={label}
        className="inline-flex max-w-32 shrink-0 items-center gap-1 truncate rounded-md bg-muted/70 px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground"
      >
        <Columns2 className="h-3 w-3 shrink-0" aria-hidden />
        {!compact && <span className="truncate">{title}</span>}
      </span>
    </HoverHint>
  );
}

export function SubtlePinMark() {
  return (
    <Pin
      className="h-3 w-3 shrink-0 text-muted-foreground/75"
      aria-hidden
    />
  );
}
