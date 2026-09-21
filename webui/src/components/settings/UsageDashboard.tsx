import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { TokenUsageModelTrend } from "@/components/settings/TokenUsageModelTrend";
import type { UsageDetails, UsageRange, UsageTotals } from "@/lib/types";
import { usageCalendar, usageModelLabel } from "@/lib/usage-dashboard";
import { cn } from "@/lib/utils";

const RANGES: UsageRange[] = ["7", "30", "365", "retained"];
const LEVELS = ["bg-muted", "bg-orange-200 dark:bg-orange-900", "bg-orange-300 dark:bg-orange-700", "bg-orange-400 dark:bg-orange-500", "bg-orange-600 dark:bg-orange-300"];

export function UsageDashboard({ load }: { load: (range: UsageRange) => Promise<UsageDetails> }) {
  const { t, i18n } = useTranslation();
  const [range, setRange] = useState<UsageRange>("30");
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{ range: UsageRange; data: UsageDetails } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setFailed(false);
    void load(range).then(data => {
      if (!cancelled) setResult({ range, data });
    }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [load, range, revision]);
  const data = result?.range === range ? result.data : null;
  const number = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const rate = (usage: UsageTotals) => usage.cache_read_observed_input_tokens > 0
    ? percent.format(usage.cache_read_tokens / usage.cache_read_observed_input_tokens) : "—";
  const days = data ? usageCalendar(data) : [];
  const unknown = data ? Math.max(0, data.totals.requests - (data.totals.reported_requests ?? 0) - (data.totals.estimated_requests ?? 0)) : 0;
  const models = data ? [
    ...data.models.map(model => ({ ...model, label: usageModelLabel(model.provider, model.model) })),
    ...(data.other_models.requests ? [{ ...data.other_models, label: t("settings.usage.otherModels") }] : []),
  ] : [];
  const metrics = data ? [
    [t("settings.usage.totalTokens"), number.format(data.totals.total_tokens)],
    [t("usageDashboard.cached"), data.totals.cache_read_observed_input_tokens ? number.format(data.totals.cache_read_tokens) : "—"],
    [t("settings.usage.cacheHitRate"), rate(data.totals)],
    [t("settings.usage.requests"), number.format(data.totals.requests)],
    [t("usageDashboard.failed"), number.format(data.totals.failed_requests ?? 0)],
    [t("usageDashboard.activeDays"), number.format(data.active_days)],
  ] : [];
  const dateTime = (value: number | null) => value == null ? "—" : new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium", timeStyle: "short", timeZone: data?.timezone ?? "UTC",
  }).format(value);
  return <div className="min-w-0 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">{t("settings.usage.shortTitle")}</h2>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("usageDashboard.range")}>
        {RANGES.map(value => <Button key={value} size="sm" variant={range === value ? "secondary" : "ghost"} className={range === value ? "ring-1 ring-inset ring-foreground/20" : undefined} aria-pressed={range === value} onClick={() => setRange(value)}>{value === "retained" ? t("usageDashboard.retained") : t("usageDashboard.days", { count: Number(value) })}</Button>)}
        <Button size="sm" variant="ghost" onClick={() => setRevision(v => v + 1)}>{t("usageDashboard.refresh")}</Button>
      </div>
    </div>
    {failed ? <p role="alert" className="text-sm text-muted-foreground">{t("usageDashboard.unavailable")}</p> : !data ? <p role="status" className="text-sm text-muted-foreground">{t("usageDashboard.loading")}</p> : <>
      <p className="text-xs text-muted-foreground">{data.start_date} – {data.end_date} · {data.timezone}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3">
        {metrics.map(([label, value]) => <div key={label} title={label === t("settings.usage.cacheHitRate") ? t("settings.usage.cacheRateHelp") : undefined}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-xl font-medium tabular-nums">{value}</dd></div>)}
      </dl>
      <p className="text-xs text-muted-foreground">{t("usageDashboard.streaks", { current: data.current_streak_days, longest: data.longest_streak_days })}</p>
      <UsageHeatmap key={`${data.start_date}:${data.end_date}`} days={days} />
      {data.model_days.length > 0 ? <TokenUsageModelTrend days={days} modelDays={data.model_days} models={data.models} /> : null}
      <p className="text-xs text-muted-foreground">{t("usageDashboard.observation", { reported: number.format(data.totals.reported_tokens ?? 0), estimated: number.format(data.totals.estimated_tokens ?? 0), unknown: number.format(unknown) })}</p>
      <section className="space-y-3">
        <h3 className="text-sm font-medium">{t("usageDashboard.models")}</h3>
        <div className="max-h-80 overflow-auto rounded-panel border border-border/60">
          <table className="w-full text-left text-xs tabular-nums">
            <caption className="sr-only">{t("usageDashboard.models")}</caption>
            <thead className="sticky top-0 bg-background"><tr>{[t("usageDashboard.model"), t("settings.usage.totalTokens"), t("settings.usage.requests"), t("usageDashboard.failed"), t("settings.usage.cacheHitRate")].map(label => <th key={label} className="whitespace-nowrap p-3 font-medium">{label}</th>)}</tr></thead>
            <tbody>{models.map(model => <tr key={model.label} className="border-t border-border/40"><th scope="row" className="max-w-64 break-all p-3 font-normal">{model.label}</th><td className="p-3">{number.format(model.total_tokens)}</td><td className="p-3">{number.format(model.requests)}</td><td className="p-3">{number.format(model.failed_requests ?? 0)}</td><td className="p-3">{rate(model)}</td></tr>)}</tbody>
          </table>
          {!models.length ? <p className="p-3 text-xs text-muted-foreground">{t("usageDashboard.noCalls")}</p> : null}
        </div>
      </section>
      <details className="rounded-panel border border-border/60 p-3">
        <summary className="cursor-pointer text-sm">{t("usageDashboard.dailyData")}</summary>
        <div className="mt-3 max-h-64 overflow-auto"><table className="w-full text-left text-xs tabular-nums"><caption className="sr-only">{t("usageDashboard.dailyData")}</caption><thead><tr>{[t("usageDashboard.date"), t("settings.usage.totalTokens"), t("settings.usage.requests"), t("usageDashboard.failed")].map(label => <th key={label} className="p-2 font-medium">{label}</th>)}</tr></thead><tbody>{days.map(day => <tr key={day.date}><th scope="row" className="whitespace-nowrap p-2 font-normal">{day.date}</th><td className="p-2">{number.format(day.usage?.total_tokens ?? 0)}</td><td className="p-2">{number.format(day.usage?.requests ?? 0)}</td><td className="p-2">{number.format(day.usage?.failed_requests ?? 0)}</td></tr>)}</tbody></table></div>
      </details>
      <div className="space-y-2 text-xs leading-relaxed text-muted-foreground">
        <p>{t("usageDashboard.coverage", { first: dateTime(data.coverage.first_call_at_ms), last: dateTime(data.coverage.last_call_at_ms), records: number.format(data.coverage.retained_requests) })}</p>
        <p>{t("usageDashboard.retention", { days: data.coverage.max_days, requests: number.format(data.coverage.max_requests) })}</p>
        <p>{t("usageDashboard.accounting")}</p>
      </div>
    </>}
  </div>;
}

function UsageHeatmap({ days }: { days: ReturnType<typeof usageCalendar> }) {
  const { t, i18n } = useTranslation();
  const [selected, setSelected] = useState(Math.max(0, days.length - 1));
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const scroll = useRef<HTMLDivElement>(null);
  const compact = days.length <= 30;
  useEffect(() => {
    if (scroll.current) scroll.current.scrollLeft = scroll.current.scrollWidth;
  }, []);
  const number = new Intl.NumberFormat(i18n.language);
  const peak = Math.max(1, ...days.map(day => day.usage?.total_tokens ?? 0));
  const offset = days.length ? (new Date(`${days[0].date}T00:00:00Z`).getUTCDay() + 6) % 7 : 0;
  const label = (day: (typeof days)[number]) => t("settings.usage.cellTitle", { date: day.date, tokens: number.format(day.usage?.total_tokens ?? 0), requests: day.usage?.requests ?? 0 });
  return <section className="space-y-3">
    <h3 className="text-sm font-medium">{t("usageDashboard.activity")}</h3>
    <div ref={scroll} className="overflow-x-auto p-1 pb-2">
      <div className={cn("grid gap-1", compact ? "w-full" : "w-max grid-flow-col grid-rows-7")}
        style={compact ? { gridTemplateColumns: `repeat(${days.length}, minmax(20px, 1fr))` } : undefined}
        role="group" aria-label={t("usageDashboard.activity")}>
        {!compact && Array.from({ length: offset }, (_, index) => <span key={`offset-${index}`} />)}
        {days.map((day, index) => {
          const value = day.usage?.total_tokens ?? 0;
          const level = day.usage?.requests ? Math.max(1, Math.ceil(value / peak * 4)) : 0;
          return <div key={day.date} className="space-y-1 text-center"><button type="button" ref={node => { buttons.current[index] = node; }}
            tabIndex={index === selected ? 0 : -1} aria-label={label(day)} aria-pressed={index === selected} title={label(day)}
            className={cn("block rounded-sm border border-foreground/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", compact ? "h-7 w-full" : "h-5 w-5", LEVELS[level], index === selected && "ring-1 ring-foreground/60")}
            onClick={() => setSelected(index)} onFocus={() => setSelected(index)}
            onKeyDown={event => {
              const step = compact ? 1 : 7;
              const target = { ArrowLeft: index - step, ArrowRight: index + step, ArrowUp: index - 1, ArrowDown: index + 1, Home: 0, End: days.length - 1 }[event.key];
              if (target == null) return;
              event.preventDefault();
              buttons.current[Math.max(0, Math.min(days.length - 1, target))]?.focus();
            }} />{compact ? <span aria-hidden className="block text-[10px] tabular-nums text-muted-foreground">{day.date.slice(8)}</span> : null}</div>;
        })}
      </div>
    </div>
    <p className="text-xs tabular-nums text-muted-foreground" role="status">{days[selected] ? label(days[selected]) : t("usageDashboard.noCalls")}</p>
    <p className="text-xs text-muted-foreground">{t("usageDashboard.heatmapHelp")}</p>
  </section>;
}
