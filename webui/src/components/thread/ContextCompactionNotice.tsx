import { Archive, CircleAlert, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { UIContextCompaction } from "@/lib/types";

interface ContextCompactionNoticeProps {
  compaction: UIContextCompaction;
}

export function ContextCompactionNotice({ compaction }: ContextCompactionNoticeProps) {
  const { t } = useTranslation();
  const title = compaction.phase === "started"
    ? t("thread.compaction.started", { defaultValue: "Compressing context…" })
    : compaction.phase === "failed"
      ? t("thread.compaction.failed", { defaultValue: "Context compaction failed" })
      : compaction.phase === "cancelled"
        ? t("thread.compaction.cancelled", { defaultValue: "Context compaction cancelled" })
        : t("thread.compaction.succeeded", { defaultValue: "Context compacted" });
  const Icon = compaction.phase === "started"
    ? LoaderCircle
    : compaction.phase === "failed"
      ? CircleAlert
      : Archive;

  return (
    <div
      role={compaction.announce ? "status" : undefined}
      aria-live={compaction.announce ? "polite" : undefined}
      aria-busy={compaction.phase === "started"}
      data-context-compaction={compaction.phase}
      className="mx-auto flex w-full max-w-[49.5rem] items-center gap-2.5 py-1 text-xs text-muted-foreground"
    >
      <span
        className={cn(
          "flex size-6 shrink-0 items-center justify-center rounded-full bg-muted/60",
          compaction.phase === "failed" && "text-destructive",
        )}
      >
        <Icon
          className={cn(
            "size-3.5",
            compaction.phase === "started" && "animate-spin motion-reduce:animate-none",
          )}
          aria-hidden
        />
      </span>
      <p className="min-w-0 font-medium leading-5 text-foreground/80">{title}</p>
    </div>
  );
}
