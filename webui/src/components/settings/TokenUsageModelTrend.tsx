import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";
import { usageFormats, usageSpeed } from "@/lib/usage-number";
import { normalizeUsageModel } from "@/lib/usage-model";
import { cn } from "@/lib/utils";
import { UsageAxis, UsageDateAxis, usageAxisTicks, usagePeakCenter } from "@/components/settings/usage-chart";

type Usage = NonNullable<SettingsPayload["usage"]>;
const COLORS = ["bg-orange-600 dark:bg-orange-500", "bg-amber-300 dark:bg-amber-300", "bg-stone-700 dark:bg-stone-300", "bg-orange-300 dark:bg-orange-200", "bg-zinc-500 dark:bg-neutral-500", "bg-neutral-400 dark:bg-neutral-600"];

export function TokenUsageModelTrend({ days, modelDays, models }: {
  days: { date: string; usage?: Usage["days"][number] }[];
  modelDays: NonNullable<Usage["model_days_30d"]>;
  models?: Usage["providers_30d"];
}) {
  const { t, i18n } = useTranslation();
  const { display, exact, compact, percent, seconds, date: formatDay } = usageFormats(i18n.language);
  const total = days.reduce((sum, day) => sum + (day.usage?.total_tokens ?? 0), 0);
  // Group by provider and normalized model, so one model is never split across
  // `openai-codex/…` and bare ids.
  const modelKey = (provider: string, model: string) => JSON.stringify([provider, normalizeUsageModel(provider, model)]);
  const modelUsage = new Map<string, { cache_read_tokens: number; cache_read_observed_input_tokens: number }>();
  for (const model of models ?? []) {
    const key = modelKey(model.provider, model.model);
    const entry = modelUsage.get(key) ?? { cache_read_tokens: 0, cache_read_observed_input_tokens: 0 };
    entry.cache_read_tokens += model.cache_read_tokens ?? 0;
    entry.cache_read_observed_input_tokens += model.cache_read_observed_input_tokens ?? 0;
    modelUsage.set(key, entry);
  }
  const dates = new Set(days.map(day => day.date));
  const totals = new Map<string, { label: string; total: number }>();
  const daily = new Map<string, Map<string, { tokens: number; measured: number; generationMs: number; ttftMs: number; timed: number; cacheRead: number; cacheObserved: number }>>();
  for (const row of modelDays) {
    if (!dates.has(row.date) || row.total_tokens <= 0) continue;
    const label = normalizeUsageModel(row.provider, row.model);
    const key = JSON.stringify([row.provider, label]);
    const item = totals.get(key) ?? { label, total: 0 };
    item.total += row.total_tokens;
    totals.set(key, item);
    type Bucket = { tokens: number; measured: number; generationMs: number; ttftMs: number; timed: number; cacheRead: number; cacheObserved: number };
    const bucket = daily.get(row.date) ?? new Map<string, Bucket>();
    const entry = bucket.get(key) ?? { tokens: 0, measured: 0, generationMs: 0, ttftMs: 0, timed: 0, cacheRead: 0, cacheObserved: 0 };
    entry.tokens += row.total_tokens;
    entry.measured += row.measured_output_tokens ?? 0;
    entry.generationMs += row.generation_ms ?? 0;
    entry.ttftMs += row.ttft_ms ?? 0;
    entry.timed += row.timed_requests ?? 0;
    entry.cacheRead += row.cache_read_tokens ?? 0;
    entry.cacheObserved += row.cache_read_observed_input_tokens ?? 0;
    bucket.set(key, entry);
    daily.set(row.date, bucket);
  }
  const series = [...totals].sort((a, b) => b[1].total - a[1].total).slice(0, 5);
  const otherLabel = t("settings.usage.otherModels", { defaultValue: "Other / unattributed" });
  const columns = days.map(day => {
    const bucket = daily.get(day.date);
    const values = series.map(([key]) => bucket?.get(key)?.tokens ?? 0);
    const stats = series.map(([key]) => {
      const entry = bucket?.get(key);
      return {
        speed: entry ? usageSpeed(entry.measured, entry.generationMs) : null,
        ttft: entry && entry.timed > 0 ? entry.ttftMs / entry.timed : null,
        hit: entry && entry.cacheObserved > 0 ? entry.cacheRead / entry.cacheObserved : null,
      };
    });
    const total = day.usage?.total_tokens ?? 0;
    return { date: day.date, total, requests: day.usage?.requests ?? 0, values: [...values, Math.max(0, total - values.reduce((a, b) => a + b, 0))], stats: [...stats, { speed: null, ttft: null, hit: null }] };
  });
  const peak = Math.max(0, ...columns.map(column => column.total));
  if (!peak || !series.length) return null;
  const labels = [...series.map(([, item]) => item.label), otherLabel];
  const color = (index: number) => index === series.length ? COLORS[5] : COLORS[index];
  const hasOther = columns.some(column => column.values[series.length] > 0);
  const title = t("settings.usage.modelTrend", { defaultValue: "Model usage over time" });
  const average = total / columns.length;
  const peakIndex = columns.findIndex(column => column.total === peak);
  const peakCenter = usagePeakCenter(columns.length, peakIndex);
  const ticks = usageAxisTicks(peak, average);
  // Missing telemetry reads as `—`; 0 tok/s would look like a stall. Value and
  // unit stay in separate columns so both line up down the tooltip.
  const speed = (value: number | null): [string, string] =>
    value == null ? ["—", ""] : [display(Math.round(value)), "tok/s"];
  const firstToken = (value: number | null): [string, string] =>
    value == null ? ["—", ""] : [seconds(value), "s"];
  const spoken = (stats: { speed: number | null; ttft: number | null; hit: number | null }) =>
    `${stats.speed == null ? "" : `, ${Math.round(stats.speed)} tok/s`}${stats.ttft == null ? "" : `, ${seconds(stats.ttft)}s to first token`}${stats.hit == null ? "" : `, ${percent(stats.hit)} cache hit`}`;
  return <section className="mt-2">
    <div className="relative pl-11">
      <div className="relative h-[clamp(144px,30vh,280px)]" data-model-usage-plot>
        <UsageAxis ticks={ticks} format={compact} gridlineAttribute="data-model-usage-gridline" />
      <div role="group" aria-label={title} className="relative grid h-full grid-cols-[repeat(30,minmax(0,1fr))]">
        <TooltipProvider delayDuration={0} disableHoverableContent>
          {columns.map(column => column.total === 0 ? (
            <span key={column.date} role="img" aria-label={`${column.date}: ${exact(0)} tokens`} />
          ) : <Tooltip key={column.date}>
            <TooltipTrigger asChild>
              <span role="img" tabIndex={0} aria-label={`${column.date}: ${exact(column.total)} tokens; ${column.values.map((value, index) => `${labels[index]}: ${exact(value)}${spoken(column.stats[index])}`).join(", ")}`} className="flex min-w-0 items-end pr-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-orange-500">
                <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-sm" style={{ height: `${column.total / peak * 100}%` }}>
                  {column.values.map((value, index) => value > 0 && <span key={index} className={cn("w-full shrink-0", color(index))} style={{ height: `${value / column.total * 100}%` }} />)}
                </span>
              </span>
            </TooltipTrigger>
            <TooltipContent className="w-[27rem] max-w-[90vw] p-3">
              <dl className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto_auto_auto_auto] items-baseline gap-x-2 gap-y-2 text-xs">
                <dt className="whitespace-nowrap text-xs font-medium">{column.date}</dt>
                <dd />
                <dd className="text-[11px] text-muted-foreground">tok/s</dd>
                <dd className="text-right text-[11px] text-muted-foreground">TTFT</dd>
                <dd className="text-[11px] text-muted-foreground">s</dd>
                <dd className="text-right text-[11px] text-muted-foreground">{t("settings.usage.cacheHitRate")}</dd>
                <dd className="text-right text-[11px] text-muted-foreground">tokens</dd>
                {column.values.map((value, index) => ({ value, index })).filter(item => item.value > 0).sort((a, b) => b.value - a.value).map(({ value, index }) => {
                  const [speedValue, speedUnit] = speed(column.stats[index].speed);
                  const [ttftValue, ttftUnit] = firstToken(column.stats[index].ttft);
                  const hit = column.stats[index].hit;
                  return <Fragment key={index}>
                    <dt className="flex min-w-0 items-start gap-2"><span aria-hidden className={cn("mt-0.5 h-3 w-1 shrink-0 rounded-full", color(index))} /><span className="break-words">{labels[index]}</span></dt><dd className="text-right tabular-nums">{speedValue}</dd><dd className="w-8 tabular-nums">{speedUnit}</dd><dd className="text-right tabular-nums">{ttftValue}</dd><dd className="w-2 tabular-nums">{ttftUnit}</dd><dd className="text-right tabular-nums">{hit == null ? "—" : percent(hit)}</dd><dd className="text-right tabular-nums">{display(value)}</dd>
                  </Fragment>;
                })}
                <dt className="col-span-6 border-t border-border/50 pt-2 font-medium">{t("settings.usage.totalTokens", { defaultValue: "Total tokens" })}</dt><dd className="border-t border-border/50 pt-2 text-right font-medium tabular-nums">{display(column.total)}</dd>
                <dt className="col-span-6 text-muted-foreground">{t("settings.usage.requests")}</dt><dd className="text-right tabular-nums text-muted-foreground">{display(column.requests)}</dd>
              </dl>
            </TooltipContent>
          </Tooltip>)}
        </TooltipProvider>
      </div>
      </div>
      <UsageDateAxis start={days[0].date} end={days[days.length - 1].date} peak={days[peakIndex].date} peakCenter={peakCenter} format={formatDay} />
    </div>
    <TooltipProvider delayDuration={0} disableHoverableContent>
      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] text-muted-foreground sm:grid-cols-3">
        {labels.map((label, index) => {
          if (index === series.length && !hasOther) return null;
          const model = index < series.length ? modelUsage.get(series[index][0]) : undefined;
          const tokens = columns.reduce((sum, column) => sum + column.values[index], 0);
          const rate = model?.cache_read_observed_input_tokens ? percent(model.cache_read_tokens / model.cache_read_observed_input_tokens) : "—";
          const parts = [
            [t("settings.usage.totalTokens"), `${display(tokens)} (${percent(tokens / total)})`],
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
