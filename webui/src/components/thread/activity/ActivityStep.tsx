import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { StreamingLabelSheen } from "@/components/MessageBubble";
import { cn } from "@/lib/utils";

export type ActivityStepTone = "neutral" | "active" | "success" | "error";

export interface ActivityStepProps {
  icon?: LucideIcon;
  marker?: ReactNode;
  label: ReactNode;
  ariaLabel?: string;
  active?: boolean;
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
  label,
  ariaLabel,
  active = false,
  tone = active ? "active" : "neutral",
  className,
  contentClassName,
  labelClassName,
  markerClassName,
  style,
}: ActivityStepProps) {
  return (
    <div
      data-testid="activity-step"
      aria-label={ariaLabel}
      className={cn(
        "relative grid min-w-0 grid-cols-[1.125rem_minmax(0,1fr)] gap-2 py-0.5 text-[13px] leading-5",
        className,
      )}
      style={style}
    >
      <span
        className={cn(
          "flex h-5 w-[1.125rem] shrink-0 items-start justify-center pt-[3px]",
        )}
        aria-hidden
      >
        {marker ?? (
          <span
            className={cn(
              "grid h-3.5 w-3.5 place-items-center rounded-full border bg-background transition-colors",
              tone === "active" && "border-muted-foreground/28 text-muted-foreground/72",
              tone === "success" && "border-emerald-500/28 text-emerald-500/78",
              tone === "error" && "border-destructive/30 text-destructive/78",
              tone === "neutral" && "border-muted-foreground/18 text-muted-foreground/50",
              markerClassName,
            )}
          >
            {Icon ? <Icon className="h-2.5 w-2.5" strokeWidth={2.15} /> : null}
          </span>
        )}
      </span>
      <div className={cn("min-w-0", contentClassName)}>
        <div
          data-testid="activity-line"
          title={typeof label === "string" ? label : undefined}
          className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap"
        >
          <StreamingLabelSheen
            active={active}
            className={cn(
              "min-w-0 flex-1 truncate font-medium",
              tone === "error" ? "text-destructive/78" : "text-muted-foreground/85",
              labelClassName,
            )}
          >
            {label}
          </StreamingLabelSheen>
        </div>
      </div>
    </div>
  );
}
