import { LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Button } from "@/components/ui/button";
import type { UIMessage } from "@/lib/types";

export function SubagentThreadView({ messages, loading, failed, isStreaming, activeTurnId, runStartedAt, onRetry }: {
  messages: UIMessage[];
  loading: boolean;
  failed: boolean;
  isStreaming: boolean;
  activeTurnId?: string | null;
  runStartedAt: number;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  return <>
    {failed ? <div role="alert" className="mb-4 flex items-center gap-2 px-5 text-sm text-destructive">
      <span>{t("thread.history.error")}</span>
      <Button type="button" variant="ghost" size="sm" onClick={onRetry}>{t("thread.history.retry")}</Button>
    </div> : loading ? <p role="status" className="flex items-center gap-2 px-5 text-sm text-muted-foreground">
      <LoaderCircle className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />{t("chat.loading")}
    </p> : null}
    <ThreadMessages messages={messages} isStreaming={isStreaming} activeTurnId={activeTurnId} runStartedAt={runStartedAt} />
  </>;
}
