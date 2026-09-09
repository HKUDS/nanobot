import { useTranslation } from "react-i18next";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TokenUsageDetails } from "@/components/settings/TokenUsageDetails";

type Usage = NonNullable<SettingsPayload["usage"]>;
const SOURCE_KEYS = ["user", "api", "cron", "dream", "system"] as const;
const SEGMENT_CLASSES = [
  "bg-orange-100 text-orange-500 dark:bg-orange-400/15 dark:text-orange-400",
  "bg-neutral-300 dark:bg-neutral-500",
  "bg-neutral-200 dark:bg-neutral-700",
  "bg-orange-500 dark:bg-orange-400",
  "bg-neutral-500 dark:bg-neutral-300",
];
const CACHE_PATTERN = { backgroundImage: "repeating-linear-gradient(135deg, transparent, transparent 3px, currentColor 3px, currentColor 4px)" };

function tokenSegments(day?: Usage["days"][number]): number[] {
  if (!day) return [0, 0, 0, 0, 0];
  const observed = day.cache_read_observed_input_tokens;
  return [day.cache_read_tokens, observed - day.cache_read_tokens,
    day.input_tokens - observed,
    day.output_tokens, Math.max(0, day.total_tokens - day.input_tokens - day.output_tokens)];
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

export function TokenUsageCard({ usage, timeZone }: { usage?: Usage; timeZone?: string }) {
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
  const peak = Math.max(0, ...days.map(day => day.usage?.total_tokens ?? 0));
  const compact = new Intl.NumberFormat(i18n.language, { notation: "compact", maximumFractionDigits: 1 });
  const exact = new Intl.NumberFormat(i18n.language);
  const percent = new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 });
  const dateFormat = new Intl.DateTimeFormat(i18n.language, { month: "short", day: "numeric", timeZone: "UTC" });
  const formatDate = (date: string) => dateFormat.format(new Date(`${date}T00:00:00Z`));
  const segmentLabels = [
    t("settings.usage.cachedInput", { defaultValue: "Cached input" }),
    t("settings.usage.cacheMiss", { defaultValue: "Cache miss" }),
    t("settings.usage.cacheUnknown", { defaultValue: "Cache unknown" }),
    t("settings.usage.outputTokens", { defaultValue: "Output" }),
    t("settings.usage.otherTokens", { defaultValue: "Other tokens" }),
  ];
  const hasOtherTokens = days.some(day => tokenSegments(day.usage)[4] > 0);
  const sourceLabels: Record<string, string> = {
    user: t("settings.usage.sources.user", { defaultValue: "Chat" }),
    api: t("settings.usage.sources.api", { defaultValue: "API" }),
    cron: t("settings.usage.sources.cron", { defaultValue: "Automations" }),
    dream: t("settings.usage.sources.dream", { defaultValue: "Memory" }),
    system: t("settings.usage.sources.system", { defaultValue: "System" }),
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
          <h3 className="text-sm font-medium">{t("settings.usage.shortTitle", { defaultValue: "Token Usage" })}</h3>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums" aria-label={usage ? `${exact.format(total)} tokens` : undefined}>
            {usage ? compact.format(total) : "—"}
          </p>
        </div>
        {usage && <TokenUsageDetails days={days} models={usage.providers_30d} modelDays={usage.model_days_30d} />}
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
            <div className="mb-2 text-right text-[11px] tabular-nums text-muted-foreground" aria-hidden>{compact.format(peak)}</div>
            <div className="relative">
            <div className="pointer-events-none absolute inset-0 flex flex-col justify-between" aria-hidden>
              {[0, 1, 2].map(line => <div key={line} className="border-t border-border/40" />)}
            </div>
            <div className="relative grid h-28 grid-cols-[repeat(30,minmax(0,1fr))] gap-1" role="group" aria-label={t("settings.usage.dailyTrend", { defaultValue: "Daily token usage" })}>
              <TooltipProvider delayDuration={120}>
                {days.map(day => {
                  const tokens = day.usage?.total_tokens ?? 0;
                  const segments = tokenSegments(day.usage);
                  const label = t("settings.usage.cellTitle", {
                    defaultValue: "{{date}}: {{tokens}} tokens, {{requests}} requests",
                    date: day.date, tokens: exact.format(tokens), requests: day.usage?.requests ?? 0,
                  });
                  return (
                    <Tooltip key={day.date}>
                      <TooltipTrigger asChild>
                        <span tabIndex={0} role="img" aria-label={`${label}; ${segments.map((value, index) => `${segmentLabels[index]}: ${exact.format(value)}`).join(", ")}`} className="group flex h-full min-w-0 items-end rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-600 dark:focus-visible:outline-orange-400">
                          <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-sm group-hover:brightness-95" style={{ height: `${tokens / peak * 100}%` }}>
                            {segments.map((value, index) => value > 0 && <span key={index} className={cn("w-full shrink-0", SEGMENT_CLASSES[index])} style={{ height: `${value / tokens * 100}%`, ...(index === 0 ? CACHE_PATTERN : {}) }} />)}
                          </span>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent className="min-w-56 p-3">
                        <div className="mb-2 flex justify-between gap-6 font-medium tabular-nums"><span>{day.date}</span><span>{exact.format(tokens)}</span></div>
                        <dl className="space-y-1.5">
                          {segments.map((value, index) => (index < 4 || value > 0) && <div key={index} className="flex items-center justify-between gap-6">
                            <dt className="flex items-center gap-2 text-muted-foreground"><span aria-hidden className={cn("size-2.5 rounded-sm", SEGMENT_CLASSES[index])} style={index === 0 ? CACHE_PATTERN : undefined} />{segmentLabels[index]}</dt>
                            <dd className="tabular-nums">{exact.format(value)}</dd>
                          </div>)}
                          <div className="flex justify-between gap-6 border-t border-border/50 pt-2">
                            <dt className="text-muted-foreground">{t("settings.usage.cacheHitRate", { defaultValue: "Cache hit rate" })}</dt>
                            <dd className="tabular-nums">{day.usage?.cache_read_observed_input_tokens ? percent.format(day.usage.cache_read_tokens / day.usage.cache_read_observed_input_tokens) : "—"}</dd>
                          </div>
                        </dl>
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </TooltipProvider>
            </div>
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-muted-foreground" aria-hidden>
              <span>{formatDate(days[0].date)}</span>
              <span>{formatDate(days[14].date)}</span>
              <span>{formatDate(today)}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-muted-foreground">
              {segmentLabels.map((label, index) => (index < 4 || hasOtherTokens) && <span key={label} className="flex items-center gap-1.5"><span aria-hidden className={cn("size-2.5 rounded-sm", SEGMENT_CLASSES[index])} style={index === 0 ? CACHE_PATTERN : undefined} />{label}</span>)}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3" aria-label={t("settings.usage.bySource", { defaultValue: "Usage by source" })}>
            {breakdown.map(([source, tokens]) => (
              <div key={source} className="flex min-w-0 items-center justify-between gap-2">
                <dt className="truncate text-muted-foreground">{sourceLabels[source]}</dt>
                <dd className="shrink-0 tabular-nums" title={`${exact.format(tokens)} tokens`}>{new Intl.NumberFormat(i18n.language, { style: "percent", maximumFractionDigits: 1 }).format(tokens / total)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </div>
  );
}
