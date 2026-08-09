import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { SettingsPayload } from "@/lib/types";

type TokenUsagePayload = NonNullable<SettingsPayload["usage"]>;
type TokenUsageDay = TokenUsagePayload["days"][number];
type TokenUsageCell = {
  date: string;
  total: number;
  estimated: number;
  requests: number;
  sources: NonNullable<TokenUsageDay["sources"]>;
  future: boolean;
};
type TokenUsageMonthLabel = {
  label: string;
  column: number;
};

const TOKEN_HEATMAP_CELLS = 371;
const TOKEN_HEATMAP_COLUMNS = Math.ceil(TOKEN_HEATMAP_CELLS / 7);
const TOKEN_USAGE_SOURCE_ORDER = ["user", "api", "cron", "dream", "system"] as const;

function addUtcDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function utcDateFromIsoDay(day: string): Date {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date));
}

function isoDayInTimeZone(date: Date, timeZone: string | undefined): string {
  if (!timeZone) return isoDay(date);
  try {
    const parts = new Intl.DateTimeFormat("en", {
      calendar: "gregory",
      numberingSystem: "latn",
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    if (values.year && values.month && values.day) {
      return [
        values.year.padStart(4, "0"),
        values.month.padStart(2, "0"),
        values.day.padStart(2, "0"),
      ].join("-");
    }
  } catch {
    // Fall through to UTC when the browser cannot resolve the configured timezone.
  }
  return isoDay(date);
}

function buildTokenUsageCalendar(
  days: TokenUsageDay[] | undefined,
  monthFormatter: Intl.DateTimeFormat,
  timeZone: string | undefined,
): { cells: TokenUsageCell[]; monthLabels: TokenUsageMonthLabel[] } {
  const byDate = new Map((days ?? []).map((day) => [day.date, day]));
  const today = utcDateFromIsoDay(isoDayInTimeZone(new Date(), timeZone));
  const end = addUtcDays(today, 6 - today.getUTCDay());
  const start = addUtcDays(end, -(TOKEN_HEATMAP_CELLS - 1));
  const monthLabels: TokenUsageMonthLabel[] = [];

  const cells = Array.from({ length: TOKEN_HEATMAP_CELLS }, (_, index) => {
    const date = addUtcDays(start, index);
    const key = isoDay(date);
    const row = byDate.get(key);
    if (date.getUTCDate() === 1) {
      monthLabels.push({
        label: monthFormatter.format(date),
        column: Math.floor(index / 7) + 1,
      });
    }
    return {
      date: key,
      total: row?.total_tokens ?? 0,
      estimated: row?.estimated_tokens ?? 0,
      requests: row?.requests ?? 0,
      sources: row?.sources ?? {},
      future: date > today,
    };
  });
  return { cells, monthLabels };
}

function tokenUsageSourceLabel(
  source: string,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (source === "user") return tx("settings.usage.sources.user", "Chat");
  if (source === "api") return tx("settings.usage.sources.api", "API");
  if (source === "cron") return tx("settings.usage.sources.cron", "Automations");
  if (source === "dream") return tx("settings.usage.sources.dream", "Memory");
  return tx("settings.usage.sources.system", "System");
}

function tokenUsageSourceBreakdown(
  cell: TokenUsageCell,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  const known = TOKEN_USAGE_SOURCE_ORDER.filter((source) => cell.sources[source]?.total_tokens > 0);
  const extra = Object.keys(cell.sources)
    .filter((source) => !TOKEN_USAGE_SOURCE_ORDER.includes(source as typeof TOKEN_USAGE_SOURCE_ORDER[number]))
    .filter((source) => cell.sources[source]?.total_tokens > 0)
    .sort();
  return [...known, ...extra]
    .map((source) => {
      const label = tokenUsageSourceLabel(source, tx);
      const tokens = formatCompactTokens(cell.sources[source]?.total_tokens ?? 0);
      return `${label} ${tokens}`;
    })
    .join(" · ");
}

function formatCompactTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(tokens >= 10_000_000 ? 0 : 1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(tokens >= 10_000 ? 0 : 1)}K`;
  return String(tokens);
}

function recentCallTimeFormatter(language: string, timeZone: string | undefined) {
  const options: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  };
  try {
    return new Intl.DateTimeFormat(language, { ...options, timeZone });
  } catch {
    return new Intl.DateTimeFormat(language, options);
  }
}

function TokenUsageDetails({
  usage,
  timeZone,
  selectedCell,
  onShowRecent,
}: {
  usage?: TokenUsagePayload;
  timeZone?: string;
  selectedCell?: TokenUsageCell;
  onShowRecent: () => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const timeFormatter = useMemo(
    () => recentCallTimeFormatter(i18n.language, timeZone),
    [i18n.language, timeZone],
  );
  const dayFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        year: "numeric",
        month: "long",
        day: "numeric",
        timeZone: "UTC",
      }),
    [i18n.language],
  );
  const recentCalls = usage?.recent_calls ?? [];
  const calls = selectedCell
    ? recentCalls.filter(
        (call) =>
          (call.day ?? isoDayInTimeZone(new Date(call.timestamp), timeZone)) === selectedCell.date,
      )
    : recentCalls.slice(0, 5);
  const hasPartialDetails = Boolean(
    selectedCell && calls.length > 0 && calls.length < selectedCell.requests,
  );
  const sourceBreakdown = selectedCell ? tokenUsageSourceBreakdown(selectedCell, tx) : "";

  return (
    <div id="token-usage-details" className="mt-7 border-t border-border/35 pt-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3
            aria-atomic="true"
            aria-live="polite"
            className="text-[14px] font-medium text-foreground/88"
          >
            {selectedCell
              ? dayFormatter.format(utcDateFromIsoDay(selectedCell.date))
              : tx("settings.usage.recentTitle", "Recent calls")}
          </h3>
          {selectedCell ? (
            <>
              <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-3">
                <div>
                  <dt className="text-[10px] leading-4 text-muted-foreground/65">
                    {tx("settings.usage.totalTokens", "Total tokens")}
                  </dt>
                  <dd className="mt-0.5 text-[18px] font-medium tabular-nums tracking-[-0.02em] text-foreground/88">
                    {formatCompactTokens(selectedCell.total)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] leading-4 text-muted-foreground/65">
                    {tx("settings.usage.requests", "Requests")}
                  </dt>
                  <dd className="mt-0.5 text-[18px] font-medium tabular-nums tracking-[-0.02em] text-foreground/88">
                    {selectedCell.requests}
                  </dd>
                </div>
              </dl>
              {sourceBreakdown ? (
                <p className="mt-3 text-[11px] leading-4 text-muted-foreground/72">
                  {sourceBreakdown}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
        {selectedCell ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onShowRecent}
            className="self-start rounded-full px-3 text-[11px] text-muted-foreground"
          >
            {tx("settings.usage.viewRecent", "View recent calls")}
          </Button>
        ) : null}
      </div>
      {calls.length === 0 ? (
        <p className="mt-4 max-w-xl text-[12px] leading-5 text-muted-foreground/70">
          {selectedCell
            ? tx(
                "settings.usage.dayDetailsUnavailable",
                "Per-call details are kept only for the 50 most recent calls. This day's total is still available above.",
              )
            : tx("settings.usage.recentEmpty", "New model calls will appear here.")}
        </p>
      ) : (
        <>
          {hasPartialDetails && selectedCell ? (
            <p className="mt-4 max-w-xl text-[12px] leading-5 text-muted-foreground/70">
              {tx(
                "settings.usage.dayDetailsPartial",
                "Showing {{shown}} of {{total}} calls. Per-call details are kept only for the 50 most recent calls.",
                { shown: calls.length, total: selectedCell.requests },
              )}
            </p>
          ) : null}
          <ol className="mt-4 divide-y divide-border/30">
            {calls.map((call, index) => {
              const estimated = (call.estimated_tokens ?? 0) > 0;
              return (
                <li
                  key={`${call.timestamp}-${call.session_key ?? call.source}-${call.iteration ?? "run"}-${index}`}
                  className="grid min-w-0 gap-1.5 py-2.5 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-4"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="text-[12px] font-medium text-foreground/78">
                        {tokenUsageSourceLabel(call.source, tx)}
                      </span>
                      {call.session_key ? (
                        <code
                          translate="no"
                          title={call.session_key}
                          className="min-w-0 max-w-full truncate font-mono text-[11px] text-muted-foreground/72"
                        >
                          {call.session_key}
                        </code>
                      ) : null}
                      {call.iteration !== undefined ? (
                        <span className="text-[11px] text-muted-foreground/62">
                          {tx("settings.usage.recentIteration", "Iteration {{count}}", {
                            count: call.iteration + 1,
                          })}
                        </span>
                      ) : null}
                    </div>
                    {call.tools?.length ? (
                      <p className="break-words text-[11px] leading-4 text-muted-foreground/62">
                        {tx("settings.usage.recentTools", "Tools: {{tools}}", {
                          tools: call.tools.join(", "),
                        })}
                      </p>
                    ) : null}
                  </div>
                  <div className="min-w-0 sm:text-end">
                    <p className="text-[12px] font-medium tabular-nums text-foreground/78">
                      {tx("settings.usage.recentTokenCount", "{{tokens}} tokens", {
                        tokens: formatCompactTokens(call.total_tokens),
                      })}
                      {estimated ? (
                        <span className="font-normal text-muted-foreground/62">
                          {` · ${tx("settings.usage.estimated", "estimated")}`}
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 text-[11px] tabular-nums text-muted-foreground/62">
                      {tx(
                        "settings.usage.recentBreakdown",
                        "{{input}} in · {{output}} out · {{cached}} cached",
                        {
                          input: formatCompactTokens(call.prompt_tokens),
                          output: formatCompactTokens(call.completion_tokens),
                          cached: formatCompactTokens(call.cached_tokens),
                        },
                      )}
                    </p>
                    <time
                      dateTime={call.timestamp}
                      className="mt-0.5 block text-[10px] tabular-nums text-muted-foreground/52"
                    >
                      {timeFormatter.format(new Date(call.timestamp))}
                    </time>
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}

function tokenUsageLevel(tokens: number, max: number): number {
  if (tokens <= 0 || max <= 0) return 0;
  const ratio = tokens / max;
  if (ratio >= 0.75) return 4;
  if (ratio >= 0.45) return 3;
  if (ratio >= 0.2) return 2;
  return 1;
}

function tokenUsageCellClass(level: number, future: boolean): string {
  if (future) return "bg-transparent ring-1 ring-neutral-200/70 dark:ring-white/[0.045]";
  if (level === 4) return "bg-sky-300 dark:bg-sky-300";
  if (level === 3) return "bg-sky-400/85 dark:bg-sky-500/80";
  if (level === 2) return "bg-sky-500/60 dark:bg-sky-700/85";
  if (level === 1) return "bg-sky-500/30 dark:bg-sky-900/80";
  return "bg-neutral-200/70 ring-1 ring-black/[0.025] dark:bg-white/[0.08] dark:ring-white/[0.035]";
}

function TokenUsageCalendar({
  usage,
  timeZone,
  selectedDate,
  onSelectDate,
}: {
  usage?: TokenUsagePayload;
  timeZone?: string;
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const monthFormatter = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { month: "short", timeZone: "UTC" }),
    [i18n.language],
  );
  const { cells, monthLabels } = useMemo(
    () => buildTokenUsageCalendar(usage?.days, monthFormatter, timeZone),
    [monthFormatter, timeZone, usage?.days],
  );
  const maxTokens = Math.max(0, ...cells.map((cell) => cell.total));
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollLeft = scroller.scrollWidth;
  }, [timeZone]);

  return (
    <div ref={scrollRef} className="mt-5 overflow-x-auto pb-2">
      <div className="w-full min-w-[1480px] px-0.5 lg:min-w-[760px]">
        <div className="relative mb-2 h-4 text-[10px] font-normal leading-4 text-muted-foreground/62" aria-hidden>
          {monthLabels.map((month) => (
            <span
              key={`${month.label}-${month.column}`}
              className="absolute top-0 whitespace-nowrap"
              style={{ left: `${((month.column - 1) / TOKEN_HEATMAP_COLUMNS) * 100}%` }}
            >
              {month.label}
            </span>
          ))}
        </div>
        <div
          role="group"
          className="grid grid-flow-col grid-rows-7 gap-1"
          style={{ gridTemplateColumns: `repeat(${TOKEN_HEATMAP_COLUMNS}, minmax(0, 1fr))` }}
          aria-label={tx("settings.usage.title", "Token activity")}
        >
          <TooltipProvider delayDuration={120} skipDelayDuration={80}>
            {cells.map((cell) => {
              const level = tokenUsageLevel(cell.total, maxTokens);
              const baseLabel = cell.future
                ? cell.date
                : tx("settings.usage.cellTitle", "{{date}}: {{tokens}} tokens, {{requests}} requests", {
                    date: cell.date,
                    tokens: formatCompactTokens(cell.total),
                    requests: cell.requests,
                  });
              const label = cell.future || cell.estimated <= 0
                ? baseLabel
                : `${baseLabel} · ${
                    cell.estimated >= cell.total
                      ? tx("settings.usage.estimated", "estimated")
                      : tx("settings.usage.includesEstimates", "includes estimates")
                  }`;
              const breakdown = cell.future ? "" : tokenUsageSourceBreakdown(cell, tx);
              const ariaLabel = breakdown ? `${label} · ${breakdown}` : label;
              const interactive = !cell.future && (cell.total > 0 || cell.requests > 0);
              if (!interactive) {
                return (
                  <span
                    key={cell.date}
                    aria-hidden
                    className={cn(
                      "aspect-square w-full rounded-[3px]",
                      tokenUsageCellClass(level, cell.future),
                    )}
                  />
                );
              }
              return (
                <Tooltip key={cell.date}>
                  <TooltipTrigger asChild>
                    <button
                      id={`token-usage-day-${cell.date}`}
                      type="button"
                      aria-label={ariaLabel}
                      aria-controls="token-usage-details"
                      aria-pressed={selectedDate === cell.date}
                      onClick={() => onSelectDate(cell.date)}
                      className={cn(
                        "aspect-square w-full cursor-pointer rounded-[3px] transition-[box-shadow,filter,transform] duration-150 hover:brightness-95 focus-visible:outline-offset-2 active:scale-[0.96] motion-reduce:transition-none",
                        tokenUsageCellClass(level, cell.future),
                        selectedDate === cell.date &&
                          "ring-2 ring-sky-700 ring-offset-2 ring-offset-settings-surface dark:ring-sky-200",
                      )}
                    />
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    align="center"
                    className="px-2.5 py-1.5 text-[11px] font-normal"
                  >
                    <span className="block">{label}</span>
                    {breakdown ? (
                      <span className="mt-1 block text-muted-foreground">{breakdown}</span>
                    ) : null}
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </TooltipProvider>
        </div>
      </div>
    </div>
  );
}

export function TokenUsageOverview({
  usage,
  timeZone,
}: {
  usage?: TokenUsagePayload;
  timeZone?: string;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const selectedDay = selectedDate
    ? usage?.days.find((day) => day.date === selectedDate)
    : undefined;
  const selectedCell = selectedDay
    ? {
        date: selectedDay.date,
        total: selectedDay.total_tokens,
        estimated: selectedDay.estimated_tokens ?? 0,
        requests: selectedDay.requests,
        sources: selectedDay.sources ?? {},
        future: false,
      }
    : undefined;

  useEffect(() => {
    if (selectedDate && !selectedDay) setSelectedDate(null);
  }, [selectedDate, selectedDay]);

  const showRecentCalls = () => {
    if (selectedDate) document.getElementById(`token-usage-day-${selectedDate}`)?.focus();
    setSelectedDate(null);
  };

  return (
    <div className="mx-auto w-full max-w-[920px]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground/90">
            {tx("settings.usage.shortTitle", "Token usage")}
          </h2>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground/72">
            {tx(
              "settings.usage.subtitle",
              "Provider-reported usage over the last 12 months. Select a day with activity to inspect its calls.",
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted-foreground/62">
          <span>{tx("settings.usage.less", "Less")}</span>
          <span className="flex items-center gap-1" aria-hidden>
            {[0, 1, 2, 3, 4].map((level) => (
              <span
                key={level}
                className={cn(
                  "h-2.5 w-2.5 rounded-[3px]",
                  tokenUsageCellClass(level, false),
                )}
              />
            ))}
          </span>
          <span>{tx("settings.usage.more", "More")}</span>
        </div>
      </div>
      <TokenUsageCalendar
        usage={usage}
        timeZone={timeZone}
        selectedDate={selectedDate}
        onSelectDate={setSelectedDate}
      />
      <TokenUsageDetails
        usage={usage}
        timeZone={timeZone}
        selectedCell={selectedCell}
        onShowRecent={showRecentCalls}
      />
    </div>
  );
}
