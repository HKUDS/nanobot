import { CircleAlert, Loader2, X } from "lucide-react";
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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
  planned: string;
  recorded: string;
  running: string;
  failed: string;
  more: (count: number) => string;
  close: string;
  noEntries: string;
  completed: string;
  system: string;
};

interface AutomationCalendarProps {
  jobs: SessionAutomationJob[];
  month: Date;
  locale: string;
  copy: CalendarCopy;
  onInspect: (job: SessionAutomationJob, trigger: HTMLElement) => void;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, amount: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + amount);
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
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-foreground">{name}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] leading-4 text-muted-foreground">
          {running ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          {failed ? <CircleAlert className="h-3 w-3" aria-hidden /> : null}
          <span className="tabular-nums">{entryTime(entry, locale)}</span>
          {compact ? <span>{status}</span> : null}
          {entry.job.protected ? <span>{copy.system}</span> : null}
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
      aria-label={`${name}, ${entryTime(entry, locale)}, ${status}${entry.job.protected ? `, ${copy.system}` : ""}`}
      aria-haspopup="dialog"
      onClick={(event) => onInspect(entry.job, event.currentTarget)}
    >
      {content}
    </button>
  );
}

function CalendarOverflowEntries({ entries, dayLabel, locale, copy, onInspect }: {
  entries: CalendarEntry[];
  dayLabel: string;
  locale: string;
  copy: CalendarCopy;
  onInspect: AutomationCalendarProps["onInspect"];
}) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const pendingSelection = useRef<SessionAutomationJob | null>(null);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          ref={triggerRef}
          type="button"
          className={cn(
            "min-h-6 w-full rounded-compact px-2 py-1 text-left text-[10px] text-muted-foreground transition-colors duration-150 hover:bg-foreground/[0.055] hover:text-foreground motion-reduce:transition-none",
            formControlFocusClassName,
          )}
        >
          {copy.more(entries.length - 3)}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        side="right"
        collisionPadding={16}
        aria-labelledby={titleId}
        className="w-80 max-w-[calc(100vw-2rem)] overscroll-contain p-2"
        onCloseAutoFocus={(event) => {
          const job = pendingSelection.current;
          pendingSelection.current = null;
          if (!job || !triggerRef.current?.isConnected) return;
          // Hand off after the day popover exits, retaining a mounted return target.
          event.preventDefault();
          onInspect(job, triggerRef.current);
        }}
      >
        <div className="mb-1 flex items-center gap-2 px-2 py-1">
          <h3 id={titleId} className="min-w-0 flex-1 text-[13px] font-semibold">{dayLabel}</h3>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label={copy.close} onClick={() => setOpen(false)}>
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        {entries.map((entry) => (
          <CalendarEntryRow
            key={entry.id}
            entry={entry}
            locale={locale}
            copy={copy}
            onInspect={(job) => {
              pendingSelection.current = job;
              setOpen(false);
            }}
            compact
          />
        ))}
      </PopoverContent>
    </Popover>
  );
}

export function AutomationCalendar({ jobs, month, locale, copy, onInspect }: AutomationCalendarProps) {
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
  const monthLabel = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(month);
  const weekdayFormatter = new Intl.DateTimeFormat(locale, { weekday: "short" });
  const dayFormatter = new Intl.DateTimeFormat(locale, { day: "numeric" });
  const agendaDateFormatter = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", weekday: "short" });
  const weekdayLabels = Array.from({ length: 7 }, (_, index) => weekdayFormatter.format(addDays(new Date(2026, 0, 5), index)));

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
    <section ref={calendarRef} className="automation-calendar overflow-hidden bg-[hsl(var(--settings-surface))]">
      <div className="automation-calendar-header bg-foreground/[0.025]">
        {wideCalendar ? <div className="automation-calendar-weekdays" aria-hidden>
          {weekdayLabels.map((label) => <div key={label}>{label}</div>)}
        </div> : null}
      </div>

      {wideCalendar ? <div className="automation-calendar-grid" aria-label={monthLabel}>
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
                    <CalendarOverflowEntries
                      entries={entries}
                      dayLabel={dayLabel}
                      locale={locale}
                      copy={copy}
                      onInspect={onInspect}
                    />
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div> : null}

      {!wideCalendar ? <div className="automation-calendar-agenda px-3 py-2 sm:px-4">
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

    </section>
  );
}
