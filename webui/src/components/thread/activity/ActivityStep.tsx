import { useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { StreamingLabelSheen } from "@/components/ui/streaming-label-sheen";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { HoverHint, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ActivityStepTone = "neutral" | "active" | "success" | "error";

export interface ActivityStepProps {
  icon?: LucideIcon;
  marker?: ReactNode;
  markerLabel?: string;
  showMarker?: boolean;
  label: ReactNode;
  detail?: string;
  detailClassName?: string;
  tooltipContent?: ReactNode;
  ariaLabel?: string;
  active?: boolean;
  animateLabel?: boolean;
  tone?: ActivityStepTone;
  className?: string;
  contentClassName?: string;
  labelClassName?: string;
  markerClassName?: string;
  style?: CSSProperties;
}

export function ActivityStep({
  icon: Icon,
  marker,
  markerLabel,
  showMarker = true,
  label,
  detail,
  detailClassName,
  tooltipContent,
  ariaLabel,
  active = false,
  animateLabel = true,
  tone = active ? "active" : "neutral",
  className,
  contentClassName,
  labelClassName,
  markerClassName,
  style,
}: ActivityStepProps) {
  const lineRef = useRef<HTMLDivElement>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const textLabel = typeof label === "string" ? [label, detail].filter(Boolean).join("\n") : undefined;
  const activityMarker = (
    <span
      className={cn(
        "flex h-5 w-[1.125rem] shrink-0 items-start justify-center pt-[3px]",
        markerLabel && ["rounded-sm", formControlFocusClassName],
      )}
      aria-hidden={markerLabel ? undefined : true}
      role={markerLabel ? "img" : undefined}
      aria-label={markerLabel}
      tabIndex={markerLabel ? 0 : undefined}
    >
      {marker ?? (
        <span
          className={cn(
            "grid h-3.5 w-3.5 place-items-center transition-colors",
            tone === "error" ? "text-destructive/[0.78]" : "text-muted-foreground",
            markerClassName,
          )}
        >
          {Icon ? <Icon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden /> : null}
        </span>
      )}
    </span>
  );
  const line = (
    <div
      ref={lineRef}
      data-testid="activity-line"
      tabIndex={typeof label === "string" ? 0 : undefined}
      aria-label={detail && typeof label === "string" ? `${label}, ${detail}` : undefined}
      className={cn(
        "flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap",
        formControlFocusClassName,
      )}
    >
      <span className={cn("flex min-w-0 flex-1 items-baseline", detail && "gap-2")}>
        <StreamingLabelSheen
          active={active && animateLabel}
          className={cn(
            "min-w-0 truncate font-medium",
            detail ? "max-w-[70%] shrink-0" : "flex-1",
            tone === "error" ? "text-destructive/[0.78]" : "text-muted-foreground",
            labelClassName,
          )}
        >
          {label}
        </StreamingLabelSheen>
        {detail ? (
          <>
            {" "}
            <span className={cn("min-w-0 flex-1 truncate font-normal text-muted-foreground", detailClassName)}>{detail}</span>
          </>
        ) : null}
      </span>
    </div>
  );

  return (
    <div
      data-testid="activity-step"
      aria-label={ariaLabel}
      className={cn(
        "relative grid min-w-0 py-0.5 text-[13px] leading-5",
        showMarker ? "grid-cols-[1.125rem_minmax(0,1fr)] gap-2" : "grid-cols-1",
        className,
      )}
      style={style}
    >
      {showMarker ? markerLabel ? (
        <HoverHint content={markerLabel}>{activityMarker}</HoverHint>
      ) : activityMarker : null}
      <div className={cn("min-w-0", contentClassName)}>
        {typeof label === "string" ? (
          <TooltipProvider>
            <Tooltip open={hintOpen} onOpenChange={(open) => {
              const truncated = Array.from(lineRef.current?.querySelectorAll<HTMLElement>(".truncate") ?? [])
                .some((element) => element.scrollWidth > element.clientWidth);
              setHintOpen(open && (truncated || tooltipContent !== undefined && tooltipContent !== textLabel));
            }}>
              <TooltipTrigger asChild>{line}</TooltipTrigger>
              <TooltipContent side="top" className="max-w-[min(32rem,calc(100vw-2rem))] whitespace-pre-wrap break-words">
                {tooltipContent ?? textLabel}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : line}
      </div>
    </div>
  );
}
