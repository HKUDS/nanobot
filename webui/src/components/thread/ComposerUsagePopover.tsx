import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SidebarPanel } from "@/components/ui/sidebar-panel";
import { ContextInspector } from "./ContextInspector";
import type { ContextSnapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ComposerContextUsage {
  estimated?: boolean;
  contextTokens: number;
  contextWindowTokens?: number;
}

export interface ComposerRoundUsage {
  inputTokens: number;
  cachedTokens?: number;
  generationMs?: number;
}

export type ComposerUsageControl = (layout: { showLabel: boolean; compactLabel: boolean }) => ReactNode;

export function ComposerUsagePopover({
  context,
  rounds,
  snapshots = [],
  onOpenFile,
  showLabel = false,
  compactLabel = false,
  sidebarHost,
  sessionKey,
  children,
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
  sessionKey?: string | null;
  children?: (renderControl: ComposerUsageControl | undefined) => ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const interactedOutside = useRef(false);
  const setOpen = (next: boolean) => { if (next) interactedOutside.current = false; setLocalOpen(next); onOpenChange?.(next); };
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const measure = () => setNarrow((sidebarHost?.clientWidth ?? window.innerWidth) < 780);
    measure();
    const observer = new ResizeObserver(measure);
    if (sidebarHost) observer.observe(sidebarHost);
    window.addEventListener("resize", measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
  }, [sidebarHost]);
  const close = () => { setOpen(false); requestAnimationFrame(() => triggerRef.current?.focus()); };
  const hasRounds = rounds.some((round) => Number.isFinite(round.inputTokens) && round.inputTokens > 0);
  const hasContext = !!context
    && Number.isFinite(context.contextTokens)
    && context.contextTokens >= 0
    && Number.isFinite(context.contextWindowTokens)
    && (context.contextWindowTokens ?? 0) > 0;
  const available = open || hasContext || hasRounds || snapshots.length > 0;

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
        percent: `${context?.estimated ? "≈" : ""}${contextPercentage}`,
      });
  const triggerLabel = contextPercentage === null
    ? detailsLabel
    : `${contextDescription}. ${detailsLabel}`;
  const ringCircumference = 2 * Math.PI * 6;
  const ringLength = ringCircumference * meterPercentage / 100;
  const renderControl: ComposerUsageControl = ({ showLabel, compactLabel }) => {
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
            {compactLabel && contextPercentage !== null ? `${context?.estimated ? "≈" : ""}${contextPercentage}%` : contextDescription}
          </span>
        ) : null}
      </button>
    );

    return <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{trigger}</TooltipTrigger>
        <TooltipContent side="top" className="text-xs">{contextDescription}</TooltipContent>
      </Tooltip>
    </TooltipProvider>;
  };

  const inspector = <ContextInspector key={sessionKey} sidebar expandable={!narrow} context={context} rounds={rounds} snapshots={snapshots}
    onOpenFile={onOpenFile ? (path) => { setOpen(false); onOpenFile(path); } : undefined} />;
  const onPanelKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); close(); }
  };

  return <>
    {children ? children(available ? renderControl : undefined) : available && renderControl({ showLabel, compactLabel })}
    {available && (narrow ? <Dialog open={open} onOpenChange={setOpen} modal={!sidebarHost}>
      <DialogContent portalContainer={sidebarHost} placement="bottom" id={panelId} aria-describedby={undefined}
        data-testid="context-sidebar"
        overlayClassName={cn("context-drawer-backdrop", sidebarHost && "absolute bg-black/25 backdrop-blur-[8px] sm:bg-transparent sm:backdrop-blur-none")}
        className="context-drawer-panel flex h-[85%] min-h-0 max-w-none flex-col gap-2 p-4 pt-5 pb-[max(1rem,env(safe-area-inset-bottom))]"
        onCloseAutoFocus={(event) => { event.preventDefault(); if (!interactedOutside.current) triggerRef.current?.focus({ preventScroll: true }); }}
        onInteractOutside={(event) => {
          if (event.target instanceof Node && triggerRef.current?.contains(event.target)) event.preventDefault();
          else interactedOutside.current = true;
        }}>
        <DialogTitle className="sr-only">{t("thread.composer.context.panelTitle")}</DialogTitle>
        {inspector}
      </DialogContent>
    </Dialog> : createPortal(<SidebarPanel open={open} width={420} floating={!sidebarHost} id={panelId}
      aria-label={t("thread.composer.context.panelTitle")} data-testid="context-sidebar" onKeyDown={onPanelKeyDown}>
      {inspector}
    </SidebarPanel>, sidebarHost ?? document.body))}
  </>;
}
