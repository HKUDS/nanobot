import { useTranslation } from "react-i18next";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";
import { usageFormats } from "@/lib/usage-number";
import { cn } from "@/lib/utils";
import { TokenUsageDetails } from "@/components/settings/TokenUsageDetails";
import { UsageAxis, UsageDateAxis, usageAxisTicks, usagePeakCenter } from "@/components/settings/usage-chart";
import { SettingsHint } from "@/components/settings/shared/SettingsHint";

type Usage = NonNullable<SettingsPayload["usage"]>;
const SOURCE_KEYS = ["user", "api", "cron", "dream", "system"] as const;
const SEGMENT_CLASSES = [
  "bg-orange-100 text-orange-500 dark:bg-orange-400/15 dark:text-orange-400",
  "bg-orange-300 dark:bg-orange-400/40",
  "bg-neutral-400 dark:bg-neutral-500",
  "bg-neutral-200 dark:bg-neutral-700",
  "bg-neutral-700 dark:bg-neutral-200",
  "bg-neutral-500 dark:bg-neutral-300",
];
const CACHE_PATTERN = { backgroundImage: "repeating-linear-gradient(135deg, transparent, transparent 3px, currentColor 3px, currentColor 4px)" };

function tokenSegments(day?: Usage["days"][number]): number[] {
  if (!day) return [0, 0, 0, 0, 0, 0];
  const observed = day.cache_read_observed_input_tokens;
  // Older backends cannot locate writes within the read-observed and unknown pools.
  const input = day.cache_miss_tokens !== undefined && day.cache_unknown_tokens !== undefined
    ? [day.cache_read_tokens, day.cache_write_tokens, day.cache_miss_tokens, day.cache_unknown_tokens]
    : [day.cache_read_tokens, 0, observed - day.cache_read_tokens, day.input_tokens - observed];
  return [...input, day.output_tokens,
    Math.max(0, day.total_tokens - day.input_tokens - day.output_tokens)];
}

function todayInTimeZone(timeZone?: string): string {
  const now = new Date();
  if (timeZone) {
    try {
      const parts = new Intl.DateTimeFormat("en", {
        calendar: "gregory", numberingSystem: "latn", timeZone,
        year: "numeric", month: "2-digit", day: "2-digit",
      }).formatToParts(now);
      const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
      return `${values.year}-${values.month}-${values.day}`;
    } catch {
      // Unrecognized configured timezones fall back to UTC.
    }
  }
  return now.toISOString().slice(0, 10);
}

export function TokenUsageCard({ usage, timeZone, onDetailsOpenChange, detailsLoading }: {
  usage?: Usage;
  timeZone?: string;
  detailsLoading?: boolean;
  onDetailsOpenChange?: (open: boolean) => void;
}) {
  const { t, i18n } = useTranslation();
  const today = todayInTimeZone(timeZone);
  const byDate = new Map(usage?.days.map(day => [day.date, day]));
  const days = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(`${today}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - 29 + index);
    const key = date.toISOString().slice(0, 10);
    return { date: key, usage: byDate.get(key) };
  });
  const total = days.reduce((sum, day) => sum + (day.usage?.total_tokens ?? 0), 0);
  const values = days.map(day => day.usage?.total_tokens ?? 0);
  const average = total / values.length;
  const peak = Math.max(0, ...values);
  const peakDay = days.reduce<(typeof days)[number] | undefined>(
    (best, day) => ((day.usage?.total_tokens ?? 0) > (best?.usage?.total_tokens ?? 0) ? day : best),
    undefined,
  );
  const peakIndex = peak > 0 ? values.indexOf(peak) : -1;
  const peakCenter = usagePeakCenter(values.length, peakIndex);
  const ticks = usageAxisTicks(peak, average);
  const { display, exact, compact, percent, date: formatDate } = usageFormats(i18n.language);
  const segmentLabels = [
    t("settings.usage.cachedInput", { defaultValue: "Cached input" }),
    t("settings.usage.cacheWrite", { defaultValue: "Cache write" }),
    t("settings.usage.cacheMiss", { defaultValue: "Cache miss" }),
    t("settings.usage.cacheUnknown", { defaultValue: "Cache status unknown" }),
    t("settings.usage.outputTokens", { defaultValue: "Output" }),
    t("settings.usage.otherTokens", { defaultValue: "Other tokens" }),
  ];
  const segmentTotals = days.reduce<number[]>(
    (sums, day) => tokenSegments(day.usage).map((value, index) => sums[index] + value),
    [0, 0, 0, 0, 0, 0],
  );
  const sourceLabels: Record<string, string> = {
    user: t("settings.usage.sources.user", { defaultValue: "Chat" }),
    api: t("settings.usage.sources.api", { defaultValue: "API" }),
    cron: t("settings.usage.sources.cron", { defaultValue: "Automations" }),
    dream: t("settings.usage.sources.dream", { defaultValue: "Memory" }),
    system: t("settings.usage.sources.system", { defaultValue: "Auxiliary calls" }),
    other: t("settings.usage.unclassified", { defaultValue: "Unclassified" }),
  };
  const sources = new Map<string, number>();
  for (const day of days) {
    let classified = 0;
    for (const [source, value] of Object.entries(day.usage?.sources ?? {})) {
      const key = SOURCE_KEYS.some(known => known === source) ? source : "other";
      sources.set(key, (sources.get(key) ?? 0) + value.total_tokens);
      classified += value.total_tokens;
    }
    const remainder = Math.max(0, (day.usage?.total_tokens ?? 0) - classified);
    sources.set("other", (sources.get("other") ?? 0) + remainder);
  }
  const breakdown = [...sources].filter(([, tokens]) => tokens > 0).sort((a, b) => b[1] - a[1]);

  return (
    <div className="min-w-0 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="flex items-baseline gap-2 text-sm font-medium">
            {t("settings.usage.shortTitle", { defaultValue: "Token usage" })}
            {usage && <span className="text-[11px] font-normal leading-none text-muted-foreground">{t("settings.usage.last30Days", { defaultValue: "Last 30 days" })}</span>}
          </h3>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums" aria-label={usage ? `${exact(total)} tokens in the last 30 days` : undefined}>
            {usage ? compact(total) : "—"}
          </p>
        </div>
        {usage && <TokenUsageDetails days={days} models={usage.providers_30d} modelDays={usage.model_days_30d} onOpenChange={onDetailsOpenChange} loading={detailsLoading} />}
      </div>

      {!usage || total === 0 ? (
        <p className="pb-2 text-sm text-muted-foreground" role="status">
          {!usage
            ? t("settings.usage.unavailable", { defaultValue: "Usage data is unavailable." })
            : t("settings.usage.noActivity", { defaultValue: "No token usage in the last 30 days." })}
        </p>
      ) : (
        <>
          <div>
            <div className="relative pl-11">
              <div className="relative h-28">
                <UsageAxis ticks={ticks} format={compact} gridlineAttribute="data-usage-gridline" />
                <div className="relative grid h-full grid-cols-[repeat(30,minmax(0,1fr))]" role="group" aria-label={t("settings.usage.dailyTrend", { defaultValue: "Daily token usage" })}>
                  <TooltipProvider delayDuration={0} disableHoverableContent>
                    {days.map(day => {
                      const tokens = day.usage?.total_tokens ?? 0;
                      const segments = tokenSegments(day.usage);
                      const label = t("settings.usage.cellTitle", {
                        defaultValue: "{{date}}: {{tokens}} tokens, {{requests}} requests",
                        date: day.date, tokens: exact(tokens), requests: day.usage?.requests ?? 0,
                      });
                      if (tokens === 0) return <span key={day.date} role="img" aria-label={label} />;
                      return (
                        <Tooltip key={day.date}>
                          <TooltipTrigger asChild>
                            <span tabIndex={0} role="img" aria-label={`${label}; ${segments.map((value, index) => `${segmentLabels[index]}: ${exact(value)}`).join(", ")}`} className="group flex h-full min-w-0 items-end pr-1 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600 dark:focus-visible:outline-orange-400">
                              <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-sm group-hover:brightness-95" style={{ height: `${tokens / peak * 100}%` }}>
                                {segments.map((value, index) => value > 0 && <span key={index} className={cn("w-full shrink-0", SEGMENT_CLASSES[index])} style={{ height: `${value / tokens * 100}%`, ...(index === 0 ? CACHE_PATTERN : {}) }} />)}
                              </span>
                            </span>
                          </TooltipTrigger>
                          <TooltipContent className="min-w-56 p-3">
                            <div className="mb-2 flex justify-between gap-6 font-medium tabular-nums"><span>{day.date}</span><span title={exact(tokens)}>{display(tokens)}</span></div>
                            <dl className="space-y-1.5">
                              {segments.map((value, index) => (index < 5 || value > 0) && <div key={index} className="flex items-center justify-between gap-6">
                                <dt className="flex items-center gap-2 text-muted-foreground"><span aria-hidden className={cn("size-2.5 shrink-0 rounded-sm", SEGMENT_CLASSES[index])} style={index === 0 ? CACHE_PATTERN : undefined} /><span>{segmentLabels[index]}</span></dt>
                                <dd className="tabular-nums" title={exact(value)}>{display(value)}</dd>
                              </div>)}
                              <div className="flex justify-between gap-6 border-t border-border/50 pt-2">
                                <dt className="text-muted-foreground">{t("settings.usage.cacheHitRate", { defaultValue: "Cache hit rate" })}</dt>
                                <dd className="tabular-nums">{day.usage?.cache_read_observed_input_tokens ? percent(day.usage.cache_read_tokens / day.usage.cache_read_observed_input_tokens) : "—"}</dd>
                              </div>
                              <div className="flex justify-between gap-6">
                                <dt className="text-muted-foreground">{t("settings.usage.requests", { defaultValue: "Requests" })}</dt>
                                <dd className="tabular-nums">
                                  {display(day.usage?.requests ?? 0)}
                                  {(day.usage?.failed_requests ?? 0) > 0 && <span className="text-muted-foreground"> ({t("settings.usage.failedRequests", { defaultValue: "{{count}} failed", count: display(day.usage?.failed_requests ?? 0) })})</span>}
                                </dd>
                              </div>
                            </dl>
                          </TooltipContent>
                        </Tooltip>
                      );
                    })}
                  </TooltipProvider>
                </div>
              </div>
              <UsageDateAxis start={days[0].date} end={today} peak={peakDay?.date ?? days[0].date} peakCenter={peakCenter} format={formatDate} />
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-muted-foreground">
              {segmentLabels.map((label, index) => segmentTotals[index] > 0 && <span key={label} className="flex items-center gap-1.5"><span aria-hidden className={cn("size-2.5 rounded-sm", SEGMENT_CLASSES[index])} style={index === 0 ? CACHE_PATTERN : undefined} />{label}</span>)}
            </div>
          </div>
          <dl className="flex flex-wrap gap-x-8 gap-y-2 text-xs" aria-label={t("settings.usage.bySource", { defaultValue: "Usage by source" })}>
            {breakdown.map(([source, tokens]) => (
              <div key={source} className="flex min-w-0 items-baseline gap-2">
                <dt className="min-w-0 break-words text-muted-foreground">
                  {source === "system" ? (
                    <SettingsHint description={t("settings.usage.systemHelp", {
                      defaultValue: "Auxiliary calls include chat title generation, other internal tasks, and calls without a recorded source.",
                    })}>{sourceLabels[source]}</SettingsHint>
                  ) : sourceLabels[source]}
                </dt>
                <dd className="shrink-0 tabular-nums" title={`${exact(tokens)} tokens`}>{tokens / total < 0.001 ? `<${percent(0.001)}` : percent(tokens / total)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  );
}
