import { useEffect, useState } from "react";
import { Check, Clock, Columns2, Pin } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HoverHint } from "@/components/ui/hover-hint";
import {
  formatElapsedDuration,
  type SessionAttentionState,
} from "@/lib/session-intelligence";
import type { SessionHandle } from "@/lib/types";
import { cn } from "@/lib/utils";
import "./session-zen.css";

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

/**
 * Single Point of Light: the ONLY chromatic signal in the workspace.
 * - recovery: warm amber steady glow
 * - running: serene breathing emerald halo (2.8s sine wave, never frantic ping)
 * - updated: soft warm terracotta dot
 * - idle: whisper-quiet neutral ink point
 */
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
  const box = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";

  if (state === "recovery") {
    const label = t("chat.activity.recovery", {
      defaultValue: "Needs your attention",
    });
    return (
      <HoverHint content={label} side="top">
        <span
          role="img"
          aria-label={label}
          className={cn("relative inline-flex shrink-0 items-center justify-center", box, className)}
        >
          <span
            aria-hidden
            className="absolute h-3 w-3 rounded-full bg-amber-500/25 dark:bg-amber-400/25"
          />
          <span
            aria-hidden
            className={cn(
              "relative rounded-full bg-amber-500 dark:bg-amber-400",
              size === "md" ? "h-2 w-2" : "h-[7px] w-[7px]",
            )}
          />
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
          className={cn("relative inline-flex shrink-0 items-center justify-center", box, className)}
        >
          <span
            aria-hidden
            className="zen-breathe-halo absolute h-3 w-3 rounded-full bg-emerald-500/25 dark:bg-emerald-400/25"
          />
          <span
            aria-hidden
            className={cn(
              "relative rounded-full bg-emerald-500/90 dark:bg-emerald-400",
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
          className={cn("inline-flex shrink-0 items-center justify-center", box, className)}
        >
          <span
            aria-hidden
            className={cn(
              "rounded-full bg-[#d97742] dark:bg-[#ea8c55]",
              size === "md" ? "h-[7px] w-[7px]" : "h-1.5 w-1.5",
            )}
          />
        </span>
      </HoverHint>
    );
  }

  return (
    <span
      aria-hidden
      className={cn("inline-flex shrink-0 items-center justify-center", box, className)}
    >
      <span className="h-[5px] w-[5px] rounded-full bg-foreground/20 dark:bg-white/25" />
    </span>
  );
}

/** Tactile circular completion button inspired by Things 3 — crisp feedback on hover & completion. */
export function ZenDoneCircle({
  completed = false,
  label,
  onClick,
  className,
}: {
  completed?: boolean;
  label: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <HoverHint content={label} side="top">
      <button
        type="button"
        aria-label={label}
        onClick={(event) => {
          event.stopPropagation();
          onClick();
        }}
        className={cn(
          "group/done relative inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-all duration-150 before:absolute before:-inset-1.5 before:content-[''] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 focus-visible:ring-offset-1",
          completed
            ? "zen-done-pop border-emerald-500 bg-emerald-500 text-white"
            : "border-foreground/25 bg-transparent text-transparent hover:border-foreground/55 hover:bg-foreground/[0.04] hover:text-foreground/75 dark:border-white/25 dark:hover:border-white/55",
          className,
        )}
      >
        <Check
          className={cn(
            "h-2.5 w-2.5 transition-transform duration-150",
            completed ? "scale-100" : "scale-75 group-hover/done:scale-100",
          )}
          strokeWidth={2.75}
          aria-hidden
        />
      </button>
    </HoverHint>
  );
}

/**
 * Obsidian-inspired sidebar drawer icon: hollow outline when collapsed,
 * filled left pane when open/pinned — clear visual state without box clutter.
 */
export function SidebarDrawerIcon({
  open,
  className,
}: {
  open: boolean;
  className?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("h-[15px] w-[15px]", className)}
    >
      <path
        d="M5.5 4h3.5v16H5.5A2.5 2.5 0 0 1 3 17.5v-11A2.5 2.5 0 0 1 5.5 4Z"
        fill="currentColor"
        stroke="none"
        className={cn(
          "origin-left transition-all duration-200 ease-out motion-reduce:transition-none",
          open ? "scale-x-100 opacity-100" : "scale-x-0 opacity-0",
        )}
      />
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

/** Calm tabular elapsed time — pure typography without loud pill chrome. */
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
        "shrink-0 font-mono text-[11px] font-normal tabular-nums text-emerald-700/90 dark:text-emerald-300/90",
        className,
      )}
    >
      {elapsed}
    </span>
  );
}

/** Ultra-quiet neutral project mark (keeps chromatic budget strictly for runtime states). */
export function ProjectDot({
  className,
}: {
  color?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-foreground/25", className)}
    />
  );
}

/** Watermark-quiet @handle without background boxes or loud underlines. */
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
        "max-w-24 shrink-0 truncate font-mono text-[11px] font-normal text-muted-foreground/55",
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
    ? `定时任务守护（${count} 个）`
    : `${count} linked automation${count > 1 ? "s" : ""}`;
  return (
    <HoverHint content={label} side="top">
      <span
        aria-label={label}
        className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground/65"
      >
        <Clock className="h-3 w-3 shrink-0" strokeWidth={1.75} aria-hidden />
        {!compact && count > 1 ? <span className="tabular-nums">{count}</span> : null}
      </span>
    </HoverHint>
  );
}

export function SplitGroupBadge({
  title,
}: {
  title: string | null;
  compact?: boolean;
}) {
  const { i18n } = useTranslation();
  if (!title) return null;
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const label = isZh ? `分屏：${title}` : `Split: ${title}`;
  return (
    <HoverHint content={label} side="top">
      <span
        aria-label={label}
        className="inline-flex shrink-0 items-center text-muted-foreground/55"
      >
        <Columns2 className="h-3 w-3 shrink-0" strokeWidth={1.75} aria-hidden />
      </span>
    </HoverHint>
  );
}

export function SubtlePinMark() {
  return (
    <Pin
      className="h-3 w-3 shrink-0 text-muted-foreground/50"
      strokeWidth={1.75}
      aria-hidden
    />
  );
}
