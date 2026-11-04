import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SidebarPanel } from "@/components/ui/sidebar-panel";
import { ContextInspector } from "./ContextInspector";
import type { ContextSnapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ComposerContextUsage {
  contextTokens: number;
  contextWindowTokens?: number;
}

export interface ComposerRoundUsage {
  id: string;
  timestamp: number;
  inputTokens: number;
  outputTokens?: number;
  cachedTokens?: number;
  estimatedTokens?: number;
  generationMs?: number;
}

interface NormalizedRoundUsage extends ComposerRoundUsage {
  cachedTokens?: number;
  outputTokens: number;
}

function normalizeRounds(
  rounds: readonly ComposerRoundUsage[],
): NormalizedRoundUsage[] {
  return rounds
    .filter((round) => Number.isFinite(round.inputTokens) && round.inputTokens > 0)
    .map((round) => ({
      ...round,
      inputTokens: Math.max(0, round.inputTokens),
      outputTokens: Number.isFinite(round.outputTokens)
        ? Math.max(0, round.outputTokens ?? 0)
        : 0,
      ...(Number.isFinite(round.cachedTokens)
        ? { cachedTokens: Math.min(round.inputTokens, Math.max(0, round.cachedTokens ?? 0)) }
        : {}),
    }));
}

export function ComposerUsagePopover({
  context,
  rounds,
  snapshots = [],
  onOpenFile,
  showLabel = false,
  compactLabel = false,
  sidebarHost,
  open: controlledOpen,
  onOpenChange,
}: {
  context: ComposerContextUsage | null;
  rounds: readonly ComposerRoundUsage[];
  snapshots?: readonly ContextSnapshot[];
  onOpenFile?: (path: string) => void;
  showLabel?: boolean;
  compactLabel?: boolean;
  sidebarHost?: HTMLElement | null;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (next: boolean) => { setLocalOpen(next); onOpenChange?.(next); };
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const sidebarRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (open && (sidebarHost?.clientWidth ?? window.innerWidth) < 780) {
      sidebarRef.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
    }
  }, [open, sidebarHost]);
  const close = () => { setOpen(false); requestAnimationFrame(() => triggerRef.current?.focus()); };
  const normalizedRounds = useMemo(() => normalizeRounds(rounds), [rounds]);
  const hasContext = !!context
    && Number.isFinite(context.contextTokens)
    && context.contextTokens >= 0
    && Number.isFinite(context.contextWindowTokens)
    && (context.contextWindowTokens ?? 0) > 0;
  if (!open && !hasContext && normalizedRounds.length === 0 && !snapshots.length) {
    return null;
  }

  const contextPercentage = hasContext
    ? Math.min(
        100,
        Math.round(context!.contextTokens / context!.contextWindowTokens! * 100),
      )
    : null;
  const meterPercentage = contextPercentage ?? 0;
  const status = meterPercentage >= 90
    ? "critical"
    : meterPercentage >= 75
      ? "caution"
      : "normal";
  const detailsLabel = t("thread.composer.context.detailsLabel", {
    defaultValue: "Open context usage",
  });
  const contextDescription = contextPercentage === null
    ? detailsLabel
    : t("thread.composer.context.tooltip", {
        defaultValue: "Context {{percent}}%",
        percent: contextPercentage,
      });
  const triggerLabel = contextPercentage === null
    ? detailsLabel
    : `${contextDescription}. ${detailsLabel}`;
  const ringCircumference = 2 * Math.PI * 6;
  const ringLength = ringCircumference * meterPercentage / 100;
  const showTextLabel = showLabel && (!compactLabel || contextPercentage !== null);
  const trigger = (
      <button
        type="button"
        ref={triggerRef}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        data-testid="composer-context-usage"
        aria-label={triggerLabel}
        className={cn(
          "touch-target inline-flex size-5 shrink-0 items-center justify-center rounded-full",
          "text-muted-foreground transition-colors hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          showTextLabel && "w-auto gap-1.5 px-2 text-xs",
        )}
      >
        {contextPercentage === null ? (
          <svg viewBox="0 0 16 16" aria-hidden="true" className="size-[15px]">
            <path
              d="M3 12V9m5 3V5m5 7V2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <svg
            viewBox="0 0 16 16"
            aria-hidden="true"
            className={cn(
              "size-[15px] shrink-0 -rotate-90",
              status === "critical" && "text-destructive",
              status === "caution" && "text-amber-600 dark:text-amber-400",
              status === "normal" && "text-muted-foreground",
            )}
          >
            <circle
              cx="8"
              cy="8"
              r="6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="opacity-20"
            />
            <circle
              cx="8"
              cy="8"
              r="6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeDasharray={`${ringLength} ${ringCircumference}`}
              data-testid="composer-context-meter"
            />
          </svg>
        )}
        {showTextLabel ? (
          <span aria-hidden className="whitespace-nowrap tabular-nums">
            {compactLabel && contextPercentage !== null ? `${contextPercentage}%` : contextDescription}
          </span>
        ) : null}
      </button>
  );

  return <TooltipProvider>
    <Tooltip>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent side="top" className="text-xs">{contextDescription}</TooltipContent>
    </Tooltip>
    {open && createPortal(
      <SidebarPanel width={420} floating={!sidebarHost} ref={sidebarRef} id={panelId} aria-label={t("thread.composer.context.panelTitle")} data-testid="context-sidebar"
        onKeyDown={(event) => { if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); close(); } }}
        >
          <ContextInspector sidebar context={context} rounds={rounds} snapshots={snapshots}
            onOpenFile={onOpenFile ? (path) => { setOpen(false); onOpenFile(path); } : undefined} />
      </SidebarPanel>, sidebarHost ?? document.body)}
  </TooltipProvider>;
}
