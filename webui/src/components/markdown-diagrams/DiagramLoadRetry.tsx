import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HoverHint } from "@/components/ui/hover-hint";

export function DiagramLoadRetry({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  const hint = t("diagram.errors.load");
  return <HoverHint content={hint}>
    <button type="button" onClick={onRetry} className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
      <RotateCw aria-hidden className="size-4" /><span className="sr-only">{hint}</span>
    </button>
  </HoverHint>;
}
