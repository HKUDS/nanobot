import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { HoverHint } from "@/components/ui/tooltip";

export function ContextReplayButton({ disabled, onPlay }: { disabled: boolean; onPlay: () => void }) {
  const { t } = useTranslation();
  const label = t("thread.composer.context.playHistory");
  return <HoverHint content={label} side="top" enabled={!disabled}><button type="button" aria-label={label} disabled={disabled} onClick={onPlay}
    className="context-inspector-surface grid size-14 shrink-0 place-items-center rounded-[20px] bg-card text-foreground/80 transition-colors enabled:hover:bg-muted enabled:hover:text-orange-500 disabled:cursor-default disabled:text-foreground/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <RotateCcw className="size-[18px]" strokeWidth={2.25} aria-hidden="true" />
  </button></HoverHint>;
}
