import { Archive, CircleAlert, LoaderCircle, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { UIContextCompaction } from "@/lib/types";

interface ContextCompactionNoticeProps {
  compaction: UIContextCompaction;
}

export function ContextCompactionNotice({ compaction }: ContextCompactionNoticeProps) {
  const { t } = useTranslation();
  const rawFallback = compaction.checkpointSource === "raw_fallback";
  const title = compaction.phase === "started"
    ? t("thread.compaction.started", { defaultValue: "Compressing context…" })
    : compaction.phase === "failed"
      ? t("thread.compaction.failed", { defaultValue: "Context compaction failed" })
      : t("thread.compaction.succeeded", { defaultValue: "Context compacted" });
  const source = compaction.phase === "succeeded"
    ? rawFallback
      ? t("thread.compaction.source.raw", { defaultValue: "Raw fallback" })
      : compaction.checkpointSource === "llm_summary"
        ? t("thread.compaction.source.llm", { defaultValue: "LLM summary" })
        : null
    : null;
  const Icon = compaction.phase === "started"
    ? LoaderCircle
    : compaction.phase === "failed"
      ? CircleAlert
      : rawFallback
        ? TriangleAlert
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
          rawFallback && compaction.phase === "succeeded"
            && "text-amber-600 dark:text-amber-400",
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
      <p className="min-w-0 leading-5">
        <span className="font-medium text-foreground/80">{title}</span>
        {source ? <span className="ml-1.5">{source}</span> : null}
      </p>
    </div>
  );
}
