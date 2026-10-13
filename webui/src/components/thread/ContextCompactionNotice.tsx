import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { UIContextCompaction } from "@/lib/types";

interface ContextCompactionNoticeProps {
  compaction: UIContextCompaction;
}

export function ContextCompactionNotice({ compaction }: ContextCompactionNoticeProps) {
  const { t } = useTranslation();
  const title = compaction.phase === "started"
    ? t("thread.compaction.started", { defaultValue: "Compressing context" })
    : compaction.phase === "failed"
      ? t("thread.compaction.failed", { defaultValue: "Context compaction failed" })
      : compaction.phase === "cancelled"
        ? t("thread.compaction.cancelled", { defaultValue: "Context compaction cancelled" })
        : t("thread.compaction.succeeded", { defaultValue: "Context compacted" });

  return (
    <div
      role={compaction.announce ? "status" : undefined}
      aria-live={compaction.announce ? "polite" : undefined}
      aria-busy={compaction.phase === "started"}
      data-context-compaction={compaction.phase}
      className="mx-auto flex w-full max-w-[49.5rem] items-center justify-center gap-3 py-2 text-xs text-muted-foreground"
    >
      <span aria-hidden className="h-px min-w-4 max-w-16 flex-1 bg-border/60" />
      <p
        className={cn(
          "min-w-0 text-center leading-5",
          compaction.phase === "failed" && "text-destructive/80",
        )}
      >
        {title}
      </p>
      <span aria-hidden className="h-px min-w-4 max-w-16 flex-1 bg-border/60" />
    </div>
  );
}
