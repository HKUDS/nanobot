import { useTranslation } from "react-i18next";

import { ThreadDivider } from "@/components/thread/ThreadDivider";
import type { UIContextCompaction } from "@/lib/types";

interface ContextCompactionNoticeProps {
  compaction: UIContextCompaction;
}

export function ContextCompactionNotice({ compaction }: ContextCompactionNoticeProps) {
  const { t } = useTranslation();
  const title = t(compaction.reason
    ? `thread.compaction.reasons.${compaction.reason}.${compaction.phase}`
    : `thread.compaction.${compaction.phase}`);

  return (
    <ThreadDivider
      role={compaction.announce ? "status" : undefined}
      aria-live={compaction.announce ? "polite" : undefined}
      aria-busy={compaction.phase === "started"}
      data-context-compaction={compaction.phase}
    >
      {compaction.phase === "failed" ? <span className="text-destructive/80">{title}</span> : title}
    </ThreadDivider>
  );
}
