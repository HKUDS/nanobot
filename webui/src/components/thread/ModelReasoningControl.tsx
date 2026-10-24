import { useTranslation } from "react-i18next";

import { SegmentedControl } from "@/components/ui/segmented-control";
import type { SessionReasoningEffort } from "@/lib/types";

export function ModelReasoningControl({ data, pending, error, onChange }: {
  data: SessionReasoningEffort | null;
  pending: boolean;
  error: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  if (!data?.options.length) return null;
  return (
    <div className="mt-1 border-t border-border/55 py-1.5">
      <div aria-busy={pending} title={t("thread.composer.reasoningScope")} className="min-w-0 overflow-hidden scrollbar-thin scrollbar-track-transparent">
        <SegmentedControl mode="radio" value={data.value ?? data.preset_value ?? ""} onChange={onChange} disabled={pending}
          ariaLabel={t("thread.composer.reasoningEffort")}
          options={data.options.map((value) => ({ value, label: value }))}
          className="min-h-7 w-full gap-0 rounded-control p-0.5"
          indicatorClassName="rounded-[calc(var(--radius-control)-2px)]"
          itemClassName="min-h-6 flex-auto rounded-[calc(var(--radius-control)-2px)] px-1.5 py-0.5 text-xs leading-5 max-sm:min-h-11" />
      </div>
      {error ? <p role="alert" className="px-1.5 py-1 text-xs text-destructive">
        {t("thread.composer.reasoningSaveFailed")}
      </p> : null}
    </div>
  );
}
