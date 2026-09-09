import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";

type ModelUsage = NonNullable<NonNullable<SettingsPayload["usage"]>["providers_30d"]>[number];

export function TokenUsageModels({ models, total }: { models?: ModelUsage[]; total: number }) {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(0);
  const number = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const rows = (models ?? []).filter(model => model.total_tokens > 0).sort((a, b) => b.total_tokens - a.total_tokens);
  const remainder = Math.max(0, total - rows.reduce((sum, model) => sum + model.total_tokens, 0));
  const pageCount = Math.max(1, Math.ceil(rows.length / 5));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleRows = rows.slice(currentPage * 5, currentPage * 5 + 5);
  const heading = t("settings.usage.byModel", { defaultValue: "Usage by model" });
  return (
    <section className="mt-2" aria-label={heading}>
      <h3 className="mb-3 text-sm font-medium">{heading}</h3>
      {rows.length === 0 ? <p className="text-xs text-muted-foreground">{t("settings.usage.modelsUnavailable", { defaultValue: "No model breakdown available." })}</p> : (
        <TooltipProvider delayDuration={120}>
          <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto_60px] gap-3 text-[10px] text-muted-foreground"><span /><span>{t("settings.usage.totalTokens")}</span><span className="text-right">{t("settings.usage.cacheHitRate")}</span></div>
          <ul className="space-y-2">
            {visibleRows.map(model => {
              const rate = model.cache_read_observed_input_tokens ? percent.format(model.cache_read_tokens / model.cache_read_observed_input_tokens) : "—";
              const parts = [
                [t("settings.usage.inputTokens", { defaultValue: "Input tokens" }), number.format(model.input_tokens)],
                [t("settings.usage.outputTokens", { defaultValue: "Output" }), number.format(model.output_tokens)],
                [t("settings.usage.cachedInput", { defaultValue: "Cached input" }), number.format(model.cache_read_tokens)],
                [t("settings.usage.cacheHitRate", { defaultValue: "Cache hit rate" }), rate],
                [t("settings.usage.requests", { defaultValue: "Requests" }), number.format(model.requests)],
                [t("settings.usage.dailyAverage", { defaultValue: "Daily average" }), number.format(Math.round(model.total_tokens / 30))],
              ];
              return <li key={JSON.stringify([model.provider, model.model])}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div tabIndex={0} role="img" aria-label={`${model.model}: ${number.format(model.total_tokens)} tokens; ${parts.map(([label, value]) => `${label}: ${value}`).join(", ")}`} className="rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                      <div className="grid grid-cols-[minmax(0,1fr)_auto_60px] items-center gap-3">
                        <p className="min-w-0 truncate text-xs font-medium">{model.model}</p>
                        <p className="text-right text-xs tabular-nums">{number.format(model.total_tokens)}<span className="mt-0.5 block text-[11px] text-muted-foreground">{total ? percent.format(model.total_tokens / total) : "—"}</span></p>
                        <p className="text-right text-xs tabular-nums">{rate}</p>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[min(320px,80vw)] p-3">
                    <p className="mb-2 break-all text-xs font-medium">{model.model}</p>
                    <dl className="space-y-1.5">{parts.map(([label, value]) => <div key={label} className="flex justify-between gap-6 text-xs"><dt className="text-muted-foreground">{label}</dt><dd className="tabular-nums">{value}</dd></div>)}</dl>
                  </TooltipContent>
                </Tooltip>
              </li>;
            })}
            {remainder > 0 && <li className="flex justify-between gap-4 text-xs text-muted-foreground"><span>{t("settings.usage.otherModels", { defaultValue: "Other / unattributed" })}</span><span className="tabular-nums">{number.format(remainder)} · {percent.format(remainder / total)}</span></li>}
          </ul>
          {pageCount > 1 && <div className="mt-3 flex items-center justify-end gap-2 text-xs tabular-nums text-muted-foreground">
            <button type="button" aria-label={t("settings.usage.previousPage", { defaultValue: "Previous page" })} disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} className="settings-hover rounded-full p-1 disabled:opacity-30"><ChevronLeft className="size-4" /></button>
            <span>{currentPage + 1} / {pageCount}</span>
            <button type="button" aria-label={t("settings.usage.nextPage", { defaultValue: "Next page" })} disabled={currentPage === pageCount - 1} onClick={() => setPage(currentPage + 1)} className="settings-hover rounded-full p-1 disabled:opacity-30"><ChevronRight className="size-4" /></button>
          </div>}
        </TooltipProvider>
      )}
    </section>
  );
}
