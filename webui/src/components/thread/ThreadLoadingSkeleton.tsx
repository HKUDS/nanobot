import { useTranslation } from "react-i18next";

import { SkeletonStatus } from "@/components/settings/shared/SkeletonStatus";

export function ThreadLoadingSkeleton() {
  const { t } = useTranslation();
  return (
    <SkeletonStatus label={t("thread.loadingConversation")} className="space-y-8 pt-12">
      <div className="thread-message-row">
        <div className="ml-auto h-10 w-2/5 rounded-floating bg-muted/60" />
      </div>
      <div className="thread-message-row space-y-3">
        <div className="h-3 w-4/5 rounded bg-muted/60" />
        <div className="h-3 w-full rounded bg-muted/60" />
        <div className="h-3 w-3/5 rounded bg-muted/60" />
      </div>
      <div className="thread-message-row space-y-3">
        <div className="h-3 w-3/4 rounded bg-muted/60" />
        <div className="h-3 w-1/2 rounded bg-muted/60" />
      </div>
    </SkeletonStatus>
  );
}
