import { GitFork } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ContextReplayButton({ disabled, onPlay }: { disabled: boolean; onPlay: () => void }) {
  const { t } = useTranslation();
  const label = t("thread.composer.context.playHistory");
  return <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onPlay}
    className="context-inspector-surface grid size-14 shrink-0 place-items-center rounded-[20px] bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-default disabled:text-muted-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <GitFork className="size-5" strokeWidth={1.75} aria-hidden="true" />
  </button>;
}
