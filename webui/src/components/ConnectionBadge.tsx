import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";

const COPY: Record<ConnectionStatus, { color: string }> = {
  idle: { color: "bg-card/40 text-muted-foreground" },
  connecting: {
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  open: {
    color: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  },
  reconnecting: {
    color: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  closed: {
    color: "bg-card/40 text-muted-foreground",
  },
  error: {
    color: "bg-destructive/10 text-destructive",
  },
};

export function ConnectionBadge() {
  const { t } = useTranslation();
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);

  useEffect(() => client.onStatus(setStatus), [client]);

  const meta = COPY[status];
  const pulsing =
    status === "connecting" ||
    status === "reconnecting" ||
    status === "error";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-border/60 px-2 py-1 text-[11px] font-medium transition-colors",
        meta.color,
      )}
      aria-live="polite"
    >
      <span className="relative flex h-1.5 w-1.5" aria-hidden>
        {pulsing && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
        )}
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
      </span>
      {t(`connection.${status}`)}
    </span>
  );
}
