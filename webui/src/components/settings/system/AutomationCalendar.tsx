import { ChevronDown, CircleAlert, Clock3, Loader2 } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { formControlFocusClassName } from "@/components/ui/form-control";
import type { SessionAutomationJob } from "@/lib/types";
import { cn } from "@/lib/utils";

type CalendarEntry = {
  id: string;
  job: SessionAutomationJob;
  startMs: number;
  endMs: number | null;
  kind: "planned" | "recorded";
  status: string | null;
};

type CalendarCopy = {
  previousMonth: string;
  nextMonth: string;
  today: string;
  planned: string;
  recorded: string;
  running: string;
  failed: string;
  more: (count: number) => string;
  noEntries: string;
  outsideMonth: string;
  paused: string;
  attention: string;
  completed: string;
};

interface AutomationCalendarProps {
  jobs: SessionAutomationJob[];
  locale: string;
  copy: CalendarCopy;
  onInspect: (job: SessionAutomationJob, trigger: HTMLElement) => void;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addDays(date: Date, amount: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + amount);
}

function addMonths(date: Date, amount: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + amount, 1);
}

function mondayIndex(date: Date): number {
  return (date.getDay() + 6) % 7;
}

function dateKey(value: Date | number): string {
  const date = typeof value === "number" ? new Date(value) : value;
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function entriesForJobs(jobs: SessionAutomationJob[]): CalendarEntry[] {
  return jobs.flatMap((job) => {
    const history = job.state.run_history ?? [];
    const nextRun = job.enabled ? job.state.next_run_at_ms : null;
    const recordedRuns = history.length || job.state.last_run_at_ms == null || nextRun != null
      ? history
      : [{
          run_at_ms: job.state.last_run_at_ms,
          status: job.state.last_status ?? "ok",
        }];
    const recorded = recordedRuns.map((run, index) => ({
      id: `${job.id}:recorded:${run.run_at_ms}:${index}`,
      job,
      startMs: run.run_at_ms,
      endMs: run.duration_ms != null && run.duration_ms > 0
        ? run.run_at_ms + run.duration_ms
        : null,
      kind: "recorded" as const,
      status: run.status ?? null,
    }));
    return nextRun == null ? recorded : [
      ...recorded,
      {
        id: `${job.id}:planned:${nextRun}`,
        job,
        startMs: nextRun,
        endMs: null,
        kind: "planned" as const,
        status: null,
      },
    ];
  });
}

function entryTime(entry: CalendarEntry, locale: string): string {
  const formatter = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" });
  const start = formatter.format(entry.startMs);
  if (entry.endMs == null) return start;
  return `${start}–${formatter.format(entry.endMs)}`;
}

function isSameDay(left: Date, right: Date): boolean {
  return dateKey(left) === dateKey(right);
}

function CalendarEntryRow({ entry, locale, copy, onInspect, compact = false }: {
  entry: CalendarEntry;
  locale: string;
  copy: CalendarCopy;
  onInspect: AutomationCalendarProps["onInspect"];
  compact?: boolean;
}) {
  const name = entry.job.name || entry.job.id;
  const running = Boolean(entry.job.state.pending) && entry.kind === "planned";
  const failed = entry.kind === "recorded" && entry.status === "error";
  const completed = entry.kind === "recorded"
    && Boolean(entry.job.delete_after_run)
    && entry.job.state.next_run_at_ms == null
    && entry.job.state.last_status === "ok";
  const status = running
    ? copy.running
    : failed
      ? copy.failed
      : completed
        ? copy.completed
        : entry.kind === "planned"
          ? copy.planned
          : copy.recorded;
  const content = (
    <>
      <span className={cn(
        "mt-[0.4rem] h-1.5 w-1.5 shrink-0 rounded-full",
        running && "bg-[hsl(var(--usage-token))]",
        failed && "bg-destructive",
        !running && !failed && entry.kind === "planned" && "border border-foreground/50 bg-background",
        !running && !failed && entry.kind === "recorded" && "bg-foreground/45",
      )} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-foreground">{name}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] leading-4 text-muted-foreground">
          {running ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          {failed ? <CircleAlert className="h-3 w-3" aria-hidden /> : null}
          <span className="tabular-nums">{entryTime(entry, locale)}</span>
          {compact ? <span>{status}</span> : null}
        </span>
      </span>
    </>
  );
  const actionClass = cn(
    "flex w-full min-w-0 items-start gap-2 rounded-compact px-2 py-1.5 text-left text-[11px] leading-4",
    "transition-colors duration-150 hover:bg-foreground/[0.055] motion-reduce:transition-none",
    formControlFocusClassName,
    compact && "py-2 text-[12px]",
    failed && "bg-destructive/[0.045]",
    entry.kind === "recorded" && !failed && "bg-muted/45",
  );

  return (
    <button
      type="button"
      className={actionClass}
      aria-label={`${name}, ${entryTime(entry, locale)}, ${status}`}
      aria-haspopup="dialog"
      onClick={(event) => onInspect(entry.job, event.currentTarget)}
    >
      {content}
    </button>
  );
}

export function AutomationCalendar({ jobs, locale, copy, onInspect }: AutomationCalendarProps) {
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const calendarRef = useRef<HTMLElement | null>(null);
  const [wideCalendar, setWideCalendar] = useState(true);
  const today = startOfDay(new Date());
  const gridStart = addDays(month, -mondayIndex(month));
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const dayCount = mondayIndex(month) + daysInMonth > 35 ? 42 : 35;
  const days = Array.from({ length: dayCount }, (_, index) => addDays(gridStart, index));
  const gridEndMs = addDays(gridStart, dayCount).getTime();
  const allEntries = useMemo(() => entriesForJobs(jobs).sort((left, right) => left.startMs - right.startMs), [jobs]);
  const visibleEntries = allEntries.filter((entry) => entry.startMs >= gridStart.getTime() && entry.startMs < gridEndMs);
  const entriesByDay = new Map<string, CalendarEntry[]>();
  visibleEntries.forEach((entry) => {
    const key = dateKey(entry.startMs);
    entriesByDay.set(key, [...(entriesByDay.get(key) ?? []), entry]);
  });
  const visibleJobIds = new Set(visibleEntries.map((entry) => entry.job.id));
  const outsideJobs = jobs.filter((job) => !visibleJobIds.has(job.id));
  const monthLabel = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(month);
  const weekdayFormatter = new Intl.DateTimeFormat(locale, { weekday: "short" });
  const dayFormatter = new Intl.DateTimeFormat(locale, { day: "numeric" });
  const agendaDateFormatter = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", weekday: "short" });
  const weekdayLabels = Array.from({ length: 7 }, (_, index) => weekdayFormatter.format(addDays(new Date(2026, 0, 5), index)));

  const inspectOutsideJob = (job: SessionAutomationJob, target: HTMLElement) => onInspect(job, target);

  useLayoutEffect(() => {
    const calendar = calendarRef.current;
    if (!calendar) return;
    const update = (width: number) => {
      if (width > 0) setWideCalendar(width >= 704);
    };
    update(calendar.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => update(entry?.contentRect.width ?? 0));
    observer.observe(calendar);
    return () => observer.disconnect();
  }, []);

  return (
    <section ref={calendarRef} className="automation-calendar overflow-hidden rounded-panel border border-border/70 bg-[hsl(var(--settings-surface))]">
      <div className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:px-6">
        <h2 className="min-w-0 flex-1 text-[15px] font-semibold text-foreground">{monthLabel}</h2>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-control px-3 text-[12px]"
            onClick={() => setMonth(startOfMonth(new Date()))}
          >
            {copy.today}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground"
            aria-label={copy.previousMonth}
            onClick={() => setMonth((value) => addMonths(value, -1))}
          >
            <span className="text-lg leading-none" aria-hidden>‹</span>
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground"
            aria-label={copy.nextMonth}
            onClick={() => setMonth((value) => addMonths(value, 1))}
          >
            <span className="text-lg leading-none" aria-hidden>›</span>
          </Button>
        </div>
      </div>

      {!jobs.length ? (
        <div className="flex min-h-48 items-center justify-center px-6 text-center text-[13px] text-muted-foreground">
          {copy.noEntries}
        </div>
      ) : null}

      {jobs.length > 0 && wideCalendar ? <div className="automation-calendar-grid" aria-label={monthLabel}>
        <div className="automation-calendar-weekdays" aria-hidden>
          {weekdayLabels.map((label) => <div key={label}>{label}</div>)}
        </div>
        <div className="automation-calendar-month">
          {days.map((day) => {
            const entries = entriesByDay.get(dateKey(day)) ?? [];
            const currentMonth = day.getMonth() === month.getMonth();
            const currentDay = isSameDay(day, today);
            const dayLabel = new Intl.DateTimeFormat(locale, { dateStyle: "full" }).format(day);
            return (
              <div
                key={dateKey(day)}
                className={cn("automation-calendar-day", !currentMonth && "bg-muted/15")}
                aria-label={dayLabel}
              >
                <div className="flex h-8 items-center justify-end px-2 pt-1">
                  <time
                    dateTime={`${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`}
                    aria-current={currentDay ? "date" : undefined}
                    className={cn(
                      "inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-[11px] tabular-nums",
                      currentDay ? "bg-foreground font-medium text-background" : currentMonth ? "text-foreground" : "text-muted-foreground/55",
                    )}
                  >
                    {dayFormatter.format(day)}
                  </time>
                </div>
                <div className="space-y-0.5 px-1 pb-1">
                  {entries.slice(0, 3).map((entry) => (
                    <CalendarEntryRow
                      key={entry.id}
                      entry={entry}
                      locale={locale}
                      copy={copy}
                      onInspect={onInspect}
                    />
                  ))}
                  {entries.length > 3 ? (
                    <details className="group/more">
                      <summary className={cn(
                        "cursor-pointer list-none rounded-control px-2 py-1 text-[10px] text-muted-foreground settings-hover [&::-webkit-details-marker]:hidden",
                        formControlFocusClassName,
                      )}>
                        {copy.more(entries.length - 3)}
                      </summary>
                      <div className="mt-0.5 space-y-0.5">
                        {entries.slice(3).map((entry) => (
                          <CalendarEntryRow
                            key={entry.id}
                            entry={entry}
                            locale={locale}
                            copy={copy}
                            onInspect={onInspect}
                          />
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div> : null}

      {jobs.length > 0 && !wideCalendar ? <div className="automation-calendar-agenda px-3 py-2 sm:px-4">
        {visibleEntries.length ? (
          <ol>
            {days.filter((day) => entriesByDay.has(dateKey(day))).map((day) => (
              <li key={dateKey(day)} className="grid grid-cols-[5.25rem_minmax(0,1fr)] gap-2 py-2.5">
                <time className={cn("pt-2 text-[11px] leading-4 text-muted-foreground", isSameDay(day, today) && "font-semibold text-foreground")}>{agendaDateFormatter.format(day)}</time>
                <div className="min-w-0 space-y-1">
                  {(entriesByDay.get(dateKey(day)) ?? []).map((entry) => (
                    <CalendarEntryRow
                      key={entry.id}
                      entry={entry}
                      locale={locale}
                      copy={copy}
                      onInspect={onInspect}
                      compact
                    />
                  ))}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <div className="flex min-h-28 items-center justify-center text-[13px] text-muted-foreground">{copy.noEntries}</div>
        )}
      </div> : null}

      {jobs.length ? (
        <div className="automation-meta-row py-2 text-[10px] text-muted-foreground">
          <span className="flex h-4 w-4 items-center justify-center" aria-hidden>
            <span className="h-1.5 w-1.5 rounded-full border border-foreground/50 bg-background" />
          </span>
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>{copy.planned}</span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-foreground/45" aria-hidden />
              {copy.recorded}
            </span>
          </span>
        </div>
      ) : null}

      {outsideJobs.length ? (
        <details
          key={`${month.getTime()}:${visibleEntries.length ? "mixed" : "outside-only"}`}
          className="group"
          open={!visibleEntries.length || undefined}
        >
          <summary className={cn("automation-meta-row min-h-11 cursor-pointer list-none items-center text-[12px] text-muted-foreground settings-hover [&::-webkit-details-marker]:hidden", formControlFocusClassName)}>
            <Clock3 className="h-3.5 w-3.5 place-self-center" aria-hidden />
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate">{copy.outsideMonth}</span>
              <span className="tabular-nums text-muted-foreground/65">{outsideJobs.length}</span>
            </span>
            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden />
          </summary>
          <ul className="px-4 pb-2 sm:px-6">
            {outsideJobs.map((job) => (
              <li key={job.id}>
                <button
                  type="button"
                  className={cn("grid min-h-10 w-full grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-x-2 rounded-control text-left text-[12px] settings-hover", formControlFocusClassName)}
                  aria-haspopup="dialog"
                  onClick={(event) => inspectOutsideJob(job, event.currentTarget)}
                >
                  <span className="h-4 w-4" aria-hidden />
                  <span className="truncate font-medium text-foreground">{job.name || job.id}</span>
                  <span className="flex shrink-0 flex-wrap justify-end gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                    {(job.state.last_status === "error" || job.state.last_error)
                      ? <span>{copy.attention}</span> : null}
                    {!job.enabled ? <span>{copy.paused}</span> : null}
                    {job.enabled && job.delete_after_run && job.state.last_status === "ok"
                      ? <span>{copy.completed}</span> : null}
                    {job.enabled && !(job.delete_after_run && job.state.last_status === "ok")
                      && job.state.last_status !== "error" && !job.state.last_error
                      ? <span>{copy.outsideMonth}</span> : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
