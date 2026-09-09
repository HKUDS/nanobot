import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

type Usage = NonNullable<SettingsPayload["usage"]>;
const COLORS = ["bg-orange-500", "bg-amber-500", "bg-stone-500", "bg-orange-300", "bg-zinc-400", "bg-neutral-200 dark:bg-neutral-600"];

export function TokenUsageModelTrend({ days, modelDays, models }: {
  days: { date: string; usage?: Usage["days"][number] }[];
  modelDays: NonNullable<Usage["model_days_30d"]>;
  models?: Usage["providers_30d"];
}) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const total = days.reduce((sum, day) => sum + (day.usage?.total_tokens ?? 0), 0);
  const modelUsage = new Map((models ?? []).map(model => [JSON.stringify([model.provider, model.model]), model]));
  const compact = new Intl.NumberFormat(i18n.language, { notation: "compact", maximumFractionDigits: 1 });
  const dates = new Set(days.map(day => day.date));
  const totals = new Map<string, { label: string; total: number }>();
  const daily = new Map<string, Map<string, number>>();
  for (const row of modelDays) {
    if (!dates.has(row.date) || row.total_tokens <= 0) continue;
    const key = JSON.stringify([row.provider, row.model]);
    const item = totals.get(key) ?? { label: row.model, total: 0 };
    item.total += row.total_tokens;
    totals.set(key, item);
    const bucket = daily.get(row.date) ?? new Map<string, number>();
    bucket.set(key, (bucket.get(key) ?? 0) + row.total_tokens);
    daily.set(row.date, bucket);
  }
  const series = [...totals].sort((a, b) => b[1].total - a[1].total).slice(0, 5);
  const otherLabel = t("settings.usage.otherModels", { defaultValue: "Other / unattributed" });
  const columns = days.map(day => {
    const bucket = daily.get(day.date);
    const values = series.map(([key]) => bucket?.get(key) ?? 0);
    const total = day.usage?.total_tokens ?? 0;
    return { date: day.date, total, requests: day.usage?.requests ?? 0, values: [...values, Math.max(0, total - values.reduce((a, b) => a + b, 0))] };
  });
  const peak = Math.max(0, ...columns.map(column => column.total));
  if (!peak || !series.length) return null;
  const labels = [...series.map(([, item]) => item.label), otherLabel];
  const color = (index: number) => index === series.length ? COLORS[5] : COLORS[index];
  const hasOther = columns.some(column => column.values[series.length] > 0);
  const title = t("settings.usage.modelTrend", { defaultValue: "Model usage over time" });
  return <section className="mt-2">
    <h3 className="mb-4 text-sm font-medium">{title}</h3>
    <div className="relative pl-9">
      <div className="pointer-events-none absolute inset-y-0 left-0 right-0 flex flex-col justify-between pb-6" aria-hidden>
        {[peak, peak / 2, 0].map((value, index) => <div key={index} className="flex items-center gap-2"><span className="w-7 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">{compact.format(value)}</span><span className="flex-1 border-t border-border/40" /></div>)}
      </div>
      <div role="group" aria-label={title} className="relative grid h-[clamp(144px,30vh,280px)] grid-cols-[repeat(30,minmax(0,1fr))] gap-px">
        <TooltipProvider delayDuration={120}>
          {columns.map(column => column.total === 0 ? (
            <span key={column.date} role="img" aria-label={`${column.date}: ${number.format(0)} tokens`} />
          ) : <Tooltip key={column.date}>
            <TooltipTrigger asChild>
              <span role="img" tabIndex={0} aria-label={`${column.date}: ${number.format(column.total)} tokens; ${column.values.map((value, index) => `${labels[index]}: ${number.format(value)}`).join(", ")}`} className="flex min-w-0 items-end focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                <span className="flex w-full flex-col-reverse" style={{ height: `${column.total / peak * 100}%` }}>
                  {column.values.map((value, index) => value > 0 && <span key={index} className={cn("w-full shrink-0", color(index))} style={{ height: `${value / column.total * 100}%` }} />)}
                </span>
              </span>
            </TooltipTrigger>
            <TooltipContent className="w-72 max-w-[85vw] p-3">
              <p className="mb-2 text-xs font-medium">{column.date}</p>
              <dl className="space-y-2">
                {column.values.map((value, index) => ({ value, index })).filter(item => item.value > 0).sort((a, b) => b.value - a.value).map(({ value, index }) => <div key={index} className="flex items-start justify-between gap-3 text-xs">
                  <dt className="flex min-w-0 items-start gap-2"><span aria-hidden className={cn("mt-0.5 h-3 w-1 shrink-0 rounded-full", color(index))} /><span className="break-words">{labels[index]}</span></dt><dd className="shrink-0 tabular-nums">{number.format(value)}</dd>
                </div>)}
                <div className="flex justify-between border-t border-border/50 pt-2 text-xs font-medium"><dt>{t("settings.usage.totalTokens", { defaultValue: "Total tokens" })}</dt><dd className="tabular-nums">{number.format(column.total)}</dd></div>
                <div className="flex justify-between text-xs text-muted-foreground"><dt>{t("settings.usage.requests")}</dt><dd className="tabular-nums">{number.format(column.requests)}</dd></div>
              </dl>
            </TooltipContent>
          </Tooltip>)}
        </TooltipProvider>
      </div>
      <div className="relative mt-2 flex justify-between text-[10px] tabular-nums text-muted-foreground"><span>{days[0].date.slice(5)}</span><span>{days[14].date.slice(5)}</span><span>{days[days.length - 1].date.slice(5)}</span></div>
    </div>
    <TooltipProvider delayDuration={120}>
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] text-muted-foreground sm:grid-cols-3">
        {labels.map((label, index) => {
          if (index === series.length && !hasOther) return null;
          const model = index < series.length ? modelUsage.get(series[index][0]) : undefined;
          const tokens = columns.reduce((sum, column) => sum + column.values[index], 0);
          const rate = model?.cache_read_observed_input_tokens ? percent.format(model.cache_read_tokens / model.cache_read_observed_input_tokens) : "—";
          const parts = [
            [t("settings.usage.totalTokens"), `${number.format(tokens)} · ${percent.format(tokens / total)}`],
            [t("settings.usage.cacheHitRate"), rate],
          ];
          return <Tooltip key={index}>
            <TooltipTrigger asChild>
              <span tabIndex={0} aria-label={`${label}: ${parts.map(([name, value]) => `${name}: ${value}`).join(", ")}`} className="flex min-w-0 items-center gap-1.5 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                <span aria-hidden className={cn("size-2 shrink-0 rounded-sm", color(index))} /><span className="truncate">{label}</span>
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-[85vw] p-3">
              <p className="mb-2 break-all text-xs font-medium">{label}</p>
              <dl className="space-y-2">{parts.map(([name, value]) => <div key={name} className="flex justify-between gap-6 text-xs"><dt className="text-muted-foreground">{name}</dt><dd className="tabular-nums">{value}</dd></div>)}</dl>
            </TooltipContent>
          </Tooltip>;
        })}
      </div>
    </TooltipProvider>
  </section>;
}
