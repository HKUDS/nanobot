import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";
import { TokenUsageModels } from "@/components/settings/TokenUsageModels";

type UsageDay = NonNullable<SettingsPayload["usage"]>["days"][number];

export function TokenUsageDetails({ days, sources, models }: {
  days: { date: string; usage?: UsageDay }[];
  sources: { label: string; tokens: number }[];
  models?: NonNullable<SettingsPayload["usage"]>["providers_30d"];
}) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const sum = (key: "total_tokens" | "input_tokens" | "output_tokens" | "requests" | "cache_read_tokens" | "cache_read_observed_input_tokens") =>
    days.reduce((total, day) => total + (day.usage?.[key] ?? 0), 0);
  const total = sum("total_tokens");
  const observed = sum("cache_read_observed_input_tokens");
  const peakRequests = Math.max(0, ...days.map(day => day.usage?.requests ?? 0));
  const requestsLabel = t("settings.usage.requests", { defaultValue: "Requests" });
  const range = `${days[0].date} – ${days[days.length - 1].date}`;
  const metrics = [
    [t("settings.usage.totalTokens", { defaultValue: "Total tokens" }), number.format(total)],
    [t("settings.usage.dailyAverage", { defaultValue: "Daily average" }), number.format(total / days.length)],
    [requestsLabel, number.format(sum("requests"))],
    [t("settings.usage.inputTokens", { defaultValue: "Input tokens" }), number.format(sum("input_tokens"))],
    [t("settings.usage.outputTokens", { defaultValue: "Output" }), number.format(sum("output_tokens"))],
    [t("settings.usage.cacheHitRate", { defaultValue: "Cache hit rate" }), observed ? percent.format(sum("cache_read_tokens") / observed) : "—"],
  ];

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button" className="settings-hover flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-xs text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
          {t("settings.usage.viewDetails", { defaultValue: "View details" })}<ChevronRight className="size-3.5" aria-hidden />
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] max-w-[640px] overflow-y-auto p-6 pt-10" aria-describedby={undefined}>
        <DialogTitle className="sr-only">{t("settings.usage.shortTitle", { defaultValue: "Token Usage" })}</DialogTitle>
        <DialogDescription className="text-xs tabular-nums">{range}</DialogDescription>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3">
          {metrics.map(([label, value]) => <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-xl font-medium tabular-nums">{value}</dd>
          </div>)}
        </dl>
        <p className="text-xs text-muted-foreground">{t("settings.usage.cacheRateHelp", { defaultValue: "Cache hit rate excludes input with unknown cache status." })}</p>
        <TokenUsageModels models={models} total={total} />
        <section className="mt-2">
          <h3 className="mb-3 text-sm font-medium">{t("settings.usage.requestTrend", { defaultValue: "Daily requests" })}</h3>
          {peakRequests === 0 ? <p className="text-sm text-muted-foreground">{number.format(0)}</p> : <>
            <div className="mb-1 text-right text-[11px] text-muted-foreground">{number.format(peakRequests)}</div>
            <div role="group" aria-label={t("settings.usage.requestTrend", { defaultValue: "Daily requests" })} className="grid h-24 grid-cols-[repeat(30,minmax(0,1fr))] gap-1 border-b border-border">
              <TooltipProvider delayDuration={120}>
                {days.map(day => {
                  const requests = day.usage?.requests ?? 0;
                  const label = `${day.date} · ${requestsLabel}: ${number.format(requests)}`;
                  return <Tooltip key={day.date}>
                    <TooltipTrigger asChild><span role="img" tabIndex={0} aria-label={label} className="flex min-w-0 items-end focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                      <span className="w-full rounded-t-sm bg-orange-500 dark:bg-orange-400" style={{ height: `${requests / peakRequests * 100}%` }} />
                    </span></TooltipTrigger>
                    <TooltipContent>{label}</TooltipContent>
                  </Tooltip>;
                })}
              </TooltipProvider>
            </div>
            <div className="mt-2 flex justify-between text-[11px] tabular-nums text-muted-foreground"><span>{days[0].date}</span><span>{days[days.length - 1].date}</span></div>
          </>}
        </section>
        {sources.length > 0 && <section className="mt-2">
          <h3 className="mb-3 text-sm font-medium">{t("settings.usage.bySource", { defaultValue: "Usage by source" })}</h3>
          <dl className="space-y-3">
            {sources.map(source => <div key={source.label}>
              <div className="mb-1.5 flex justify-between gap-4 text-xs"><dt>{source.label}</dt><dd className="tabular-nums">{number.format(source.tokens)} <span className="ml-2 text-muted-foreground">{percent.format(source.tokens / total)}</span></dd></div>
              <div className="h-1 rounded-full bg-muted" aria-hidden><div className="h-full rounded-full bg-neutral-400 dark:bg-neutral-500" style={{ width: `${source.tokens / total * 100}%` }} /></div>
            </div>)}
          </dl>
        </section>}
      </DialogContent>
    </Dialog>
  );
}
