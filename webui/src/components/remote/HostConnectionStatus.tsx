import { CircleAlert, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

export type HostConnectionState = "open" | "closed" | "connecting" | "error";

/** Connectivity is independent of which host the user is currently viewing. */
export function HostConnectionStatus({ state, compact = false }: {
  state: HostConnectionState;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const label = t(`connection.${state}`);
  return <span role="status" title={compact ? label : undefined} className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
    {state === "connecting" ? <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
      : state === "error" ? <CircleAlert aria-hidden className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
      : <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", state === "open" ? "bg-emerald-500" : "bg-muted-foreground/40")} />}
    <span className={compact ? "sr-only" : undefined}>{label}</span>
  </span>;
}
