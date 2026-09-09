import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";

type ModelUsage = NonNullable<NonNullable<SettingsPayload["usage"]>["providers_30d"]>[number];

export function TokenUsageModels({ models, total }: { models?: ModelUsage[]; total: number }) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const rows = (models ?? []).filter(model => model.total_tokens > 0).sort((a, b) => b.total_tokens - a.total_tokens);
  const remainder = Math.max(0, total - rows.reduce((sum, model) => sum + model.total_tokens, 0));
  const maximum = Math.max(1, remainder, ...rows.map(model => model.total_tokens));
  const heading = t("settings.usage.byModel", { defaultValue: "Usage by model" });
  return (
    <section className="mt-2" aria-label={heading}>
      <h3 className="mb-3 text-sm font-medium">{heading}</h3>
      {rows.length === 0 ? <p className="text-xs text-muted-foreground">{t("settings.usage.modelsUnavailable", { defaultValue: "No model breakdown available." })}</p> : (
        <TooltipProvider delayDuration={120}>
          <ul className="space-y-4">
            {rows.map(model => {
              const rate = model.cache_read_observed_input_tokens ? percent.format(model.cache_read_tokens / model.cache_read_observed_input_tokens) : "—";
              const parts = [
                [t("settings.usage.inputTokens", { defaultValue: "Input tokens" }), number.format(model.input_tokens)],
                [t("settings.usage.outputTokens", { defaultValue: "Output" }), number.format(model.output_tokens)],
                [t("settings.usage.cachedInput", { defaultValue: "Cached input" }), number.format(model.cache_read_tokens)],
                [t("settings.usage.cacheHitRate", { defaultValue: "Cache hit rate" }), rate],
                [t("settings.usage.requests", { defaultValue: "Requests" }), number.format(model.requests)],
              ];
              return <li key={JSON.stringify([model.provider, model.model])}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div tabIndex={0} role="img" aria-label={`${model.provider} · ${model.model}: ${number.format(model.total_tokens)} tokens; ${parts.map(([label, value]) => `${label}: ${value}`).join(", ")}`} className="rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                      <div className="mb-2 flex items-baseline justify-between gap-4">
                        <div className="min-w-0"><p className="truncate text-xs font-medium">{model.model}</p><p className="mt-0.5 text-[11px] text-muted-foreground">{model.provider}</p></div>
                        <p className="shrink-0 text-xs tabular-nums">{number.format(model.total_tokens)} <span className="ml-2 inline-block w-12 text-right text-muted-foreground">{total ? percent.format(model.total_tokens / total) : "—"}</span></p>
                      </div>
                      <div className="h-2 rounded-sm bg-muted" aria-hidden><div className="flex h-full overflow-hidden rounded-sm" style={{ width: `${model.total_tokens / maximum * 100}%` }}>
                        <span className="h-full bg-orange-100 text-orange-500 dark:bg-orange-400/15 dark:text-orange-400" style={{ width: `${model.total_tokens ? model.cache_read_tokens / model.total_tokens * 100 : 0}%`, backgroundImage: "repeating-linear-gradient(135deg, transparent, transparent 3px, currentColor 3px, currentColor 4px)" }} />
                        <span className="h-full flex-1 bg-orange-500 dark:bg-orange-400" />
                      </div></div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[min(320px,80vw)] p-3">
                    <p className="mb-2 break-all text-xs font-medium">{model.provider} · {model.model}</p>
                    <dl className="space-y-1.5">{parts.map(([label, value]) => <div key={label} className="flex justify-between gap-6 text-xs"><dt className="text-muted-foreground">{label}</dt><dd className="tabular-nums">{value}</dd></div>)}</dl>
                  </TooltipContent>
                </Tooltip>
              </li>;
            })}
            {remainder > 0 && <li className="flex justify-between gap-4 text-xs text-muted-foreground"><span>{t("settings.usage.otherModels", { defaultValue: "Other / unattributed" })}</span><span className="tabular-nums">{number.format(remainder)} · {percent.format(remainder / total)}</span></li>}
          </ul>
        </TooltipProvider>
      )}
    </section>
  );
}
