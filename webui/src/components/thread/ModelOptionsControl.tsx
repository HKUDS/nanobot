import { useTranslation } from "react-i18next";

import { SegmentedControl } from "@/components/ui/segmented-control";
import type { ModelOptionsCapability, SessionModelOptions } from "@/lib/types";

export interface ModelOptionsControlProps {
  data: { value: SessionModelOptions; capability: ModelOptionsCapability; efforts: string[] } | null;
  onChange: (value: SessionModelOptions) => void;
}

const INHERIT = ":inherit";
const groupClass = "grid w-full gap-0.5 rounded-control p-0.5";
const itemClass = "min-h-7 rounded-[calc(var(--radius-control)-2px)] px-1.5 py-0.5 text-xs max-sm:min-h-11";

export function ModelOptionsControl({ data, onChange }: ModelOptionsControlProps) {
  const { t } = useTranslation();
  if (!data || (!data.efforts.length && !data.value.reasoning_effort && !data.capability.codex_fast_mode)) return null;
  const { value, capability, efforts } = data;
  const inherit = t("thread.composer.modelOptions.inherit");
  const on = t("thread.composer.modelOptions.on");
  const off = t("thread.composer.modelOptions.off");
  // Persisted custom effort values remain visible even if recommendations change.
  const values = [...new Set([...efforts, ...(value.reasoning_effort ? [value.reasoning_effort] : [])])];
  return (
    <div className="mt-1 space-y-2 overflow-y-auto border-t border-border/55 py-2 scrollbar-thin scrollbar-track-transparent" title={t("thread.composer.modelOptions.scope")}>
      <p className="px-2.5 text-[11px] text-muted-foreground">{t("thread.composer.modelOptions.title")}</p>
      {values.length > 0 ? (
        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-2 px-2.5 text-xs">
            <span>{t("settings.models.reasoningEffort")}</span>
            <span className="truncate text-muted-foreground">{capability.reasoning_effort.default ?? inherit}</span>
          </div>
          <SegmentedControl mode="radio" value={value.reasoning_effort ?? INHERIT}
            onChange={(next) => onChange({ ...value, reasoning_effort: next === INHERIT ? null : next })}
            ariaLabel={t("settings.models.reasoningEffort")}
            options={[{ value: INHERIT, label: inherit }, ...values.map((effort) => ({ value: effort, label: effort }))]}
            className={`${groupClass} grid-cols-3`}
            indicatorClassName="rounded-[calc(var(--radius-control)-2px)]" itemClassName={itemClass} />
        </div>
      ) : null}
      {capability.codex_fast_mode ? (
        <div className="space-y-1">
          <div className="flex items-baseline justify-between gap-2 px-2.5 text-xs">
            <span title={t("settings.providers.capabilityFastModeHelp")}>{t("thread.composer.modelOptions.codexFast")}</span>
            <span className="text-muted-foreground">{capability.codex_fast_mode.default ? on : off}</span>
          </div>
          <SegmentedControl mode="radio"
            value={value.codex_fast_mode === null ? INHERIT : value.codex_fast_mode ? "on" : "off"}
            onChange={(next) => onChange({ ...value, codex_fast_mode: next === INHERIT ? null : next === "on" })}
            ariaLabel={t("thread.composer.modelOptions.codexFast")}
            options={[
              { value: INHERIT, label: inherit }, { value: "on", label: on }, { value: "off", label: off },
            ].map((option) => ({ ...option, tooltip: t("settings.providers.capabilityFastModeHelp") }))}
            className={`${groupClass} grid-cols-3`}
            indicatorClassName="rounded-[calc(var(--radius-control)-2px)]" itemClassName={itemClass} />
        </div>
      ) : null}
    </div>
  );
}
