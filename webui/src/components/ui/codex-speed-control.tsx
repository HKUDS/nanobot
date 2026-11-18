import { Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/hover-hint";
import type { CodexFastMode } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CodexSpeedControl({ value, onChange, ultrafastSupported }: {
  value: CodexFastMode;
  onChange: (value: CodexFastMode) => void;
  ultrafastSupported?: boolean;
}) {
  const { t } = useTranslation();
  const title = t("thread.composer.modelOptions.codexFast");
  const help = t("settings.providers.capabilityFastModeHelp");
  const modes = ultrafastSupported || value === "ultrafast" ? [true, "ultrafast"] as const : [true] as const;
  return (
    <div role="group" aria-label={title} className="inline-flex items-center gap-0.5">
      {modes.map((mode) => {
        const ultra = mode === "ultrafast";
        const label = ultra ? t("thread.composer.modelOptions.ultrafast") : title;
        const selected = value === mode;
        return (
          <HoverHint key={String(mode)} content={<><strong className="block">{label}</strong>{help}</>}>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={label}
              aria-pressed={selected}
              className="group/speed h-8 w-8 rounded-lg p-0 max-sm:h-11 max-sm:w-11"
              onClick={() => onChange(selected ? false : mode)}
            >
              <span aria-hidden className={cn(
                "grid size-7 place-items-center rounded-md",
                selected ? "bg-foreground text-background" : "bg-muted/65 text-muted-foreground group-hover/speed:text-foreground",
              )}>
                {ultra ? (
                  <span className="relative size-[18px]">
                    <Zap className="absolute left-0 top-0 size-3.5 opacity-60" />
                    <Zap className="absolute bottom-0 right-0 size-3.5" />
                  </span>
                ) : <Zap className="size-4" />}
              </span>
            </Button>
          </HoverHint>
        );
      })}
    </div>
  );
}
