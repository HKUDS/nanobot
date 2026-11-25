import { RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";

export function DiagramLoadRetry({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <RotateCw aria-hidden="true" className="size-3.5 shrink-0" />{t("diagram.errors.load")}
  </button>;
}
