import { CalendarDays, ChevronLeft, ChevronRight, Clock3 } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

function dateKey(date: Date): string {
  return `${String(date.getFullYear()).padStart(4, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function localDay(year: number, month: number, day: number): Date {
  const date = new Date(0);
  date.setHours(12, 0, 0, 0);
  date.setFullYear(year, month, day);
  return date;
}

function parseDay(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = localDay(year, month - 1, day);
  return year > 0 && dateKey(date) === value ? date : null;
}

export function parseAutomationRunAt(value: string): Date | null {
  const [day, time, extra] = value.split("T");
  const date = parseDay(day);
  if (!date || extra !== undefined || !/^([01]\d|2[0-3]):[0-5]\d$/.test(time ?? "")) return null;
  const [hour, minute] = time.split(":").map(Number);
  date.setHours(hour, minute, 0, 0);
  // Reject impossible dates and local times instead of silently rolling forward.
  return dateKey(date) === day && date.getHours() === hour && date.getMinutes() === minute ? date : null;
}

function moveMonth(date: Date, amount: number): Date {
  const month = localDay(date.getFullYear(), date.getMonth() + amount, 1);
  const lastDay = localDay(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  month.setDate(Math.min(date.getDate(), lastDay));
  return month;
}

export function AutomationRunAtPicker({ value, onChange, disabled = false, errorId }: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  errorId?: string;
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage || i18n.language;
  const id = useId();
  const [open, setOpen] = useState(false);
  const [focusedDay, setFocusedDay] = useState(() => parseDay(value.split("T")[0]) ?? new Date());
  const activeDay = useRef<HTMLButtonElement | null>(null);
  const restoreGridFocus = useRef(false);
  const [dateValue, timeValue = ""] = value.split("T");
  const month = localDay(focusedDay.getFullYear(), focusedDay.getMonth(), 1);
  const weekStart = (month.getDay() + 6) % 7;
  const monthLabel = new Intl.DateTimeFormat(locale, { year: "numeric", month: "long" }).format(month);
  const dayFormatter = new Intl.DateTimeFormat(locale, { dateStyle: "full" });
  const weekdays = Array.from({ length: 7 }, (_, index) => localDay(2026, 0, 5 + index));
  const todayKey = dateKey(new Date());

  useLayoutEffect(() => {
    if (restoreGridFocus.current) {
      activeDay.current?.focus({ preventScroll: true });
      restoreGridFocus.current = false;
    }
  }, [focusedDay]);

  const navigate = (next: Date, focus = false) => {
    if (next.getFullYear() < 1 || next.getFullYear() > 9999) return;
    restoreGridFocus.current = focus;
    setFocusedDay(next);
  };
  const selectDay = (day: Date) => {
    onChange(`${dateKey(day)}T${timeValue}`);
    setOpen(false);
  };
  const onDayKeyDown = (event: KeyboardEvent<HTMLButtonElement>, day: Date) => {
    const next = new Date(day);
    const weekday = (day.getDay() + 6) % 7;
    const rtl = i18n.dir(locale) === "rtl";
    switch (event.key) {
      case "ArrowLeft": next.setDate(day.getDate() + (rtl ? 1 : -1)); break;
      case "ArrowRight": next.setDate(day.getDate() + (rtl ? -1 : 1)); break;
      case "ArrowUp": next.setDate(day.getDate() - 7); break;
      case "ArrowDown": next.setDate(day.getDate() + 7); break;
      case "Home": next.setDate(day.getDate() - weekday); break;
      case "End": next.setDate(day.getDate() + 6 - weekday); break;
      case "PageUp": case "PageDown":
        event.preventDefault();
        navigate(moveMonth(day, (event.key === "PageUp" ? -1 : 1) * (event.shiftKey ? 12 : 1)), true);
        return;
      default: return;
    }
    event.preventDefault();
    navigate(next, true);
  };

  return (
    <fieldset className="automation-run-at-picker min-w-0" disabled={disabled}>
      <legend className="mb-1.5 text-[12px] font-medium text-muted-foreground">{t("settings.automations.fields.runAt")}</legend>
      <div className="automation-run-at-fields grid min-w-0 gap-2">
        <div className="relative min-w-0">
          <label htmlFor={`${id}-date`} className="sr-only">{t("settings.automations.fields.runDate")}</label>
          <Input id={`${id}-date`} type="text" value={dateValue} placeholder="YYYY-MM-DD"
            aria-describedby={errorId}
            aria-invalid={dateValue !== "" && !parseDay(dateValue) || undefined}
            autoComplete="off" spellCheck={false} className="pe-11 text-[16px] tabular-nums sm:text-[13px]"
            onChange={(event) => onChange(`${event.target.value}T${timeValue}`)} />
          <Popover open={open} onOpenChange={(next) => {
            setOpen(next);
            if (next) setFocusedDay(parseDay(dateValue) ?? new Date());
          }}>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost" size="icon" disabled={disabled}
                aria-label={t("settings.automations.fields.chooseDate")}
                className="absolute end-1 top-1 h-8 w-8 rounded-full text-muted-foreground">
                <CalendarDays className="h-4 w-4" aria-hidden />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" collisionPadding={12} aria-label={t("settings.automations.fields.chooseDate")}
              data-automation-date-calendar=""
              className="w-72 max-w-[calc(100vw-2rem)] overscroll-contain p-3"
              onEscapeKeyDown={(event) => {
                event.preventDefault();
                setOpen(false);
              }}
              onOpenAutoFocus={(event) => { event.preventDefault(); activeDay.current?.focus({ preventScroll: true }); }}>
              <div className="mb-2 flex items-center gap-1">
                <span id={`${id}-month`} aria-live="polite" className="min-w-0 flex-1 ps-2 text-[13px] font-semibold">{monthLabel}</span>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0"
                  disabled={month.getFullYear() === 1 && month.getMonth() === 0}
                  aria-label={t("settings.automations.calendar.previousMonth")}
                  onClick={() => navigate(moveMonth(focusedDay, -1))}>
                  <ChevronLeft className="h-4 w-4 rtl:rotate-180" aria-hidden />
                </Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0"
                  disabled={month.getFullYear() === 9999 && month.getMonth() === 11}
                  aria-label={t("settings.automations.calendar.nextMonth")}
                  onClick={() => navigate(moveMonth(focusedDay, 1))}>
                  <ChevronRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
                </Button>
              </div>
              <table role="grid" aria-labelledby={`${id}-month`} className="w-full table-fixed border-collapse text-center text-[12px]">
                <thead><tr>{weekdays.map((day) => (
                  <th key={day.getDay()} scope="col" className="h-8 font-normal text-muted-foreground"
                    aria-label={new Intl.DateTimeFormat(locale, { weekday: "long" }).format(day)}>
                    {new Intl.DateTimeFormat(locale, { weekday: "short" }).format(day)}
                  </th>
                ))}</tr></thead>
                <tbody>{Array.from({ length: 6 }, (_, week) => (
                  <tr key={week}>{Array.from({ length: 7 }, (_, column) => {
                    const day = localDay(month.getFullYear(), month.getMonth(), 1 - weekStart + week * 7 + column);
                    const key = dateKey(day);
                    const selected = key === dateValue;
                    const focused = key === dateKey(focusedDay);
                    return <td key={key} role="gridcell" aria-selected={selected} className="p-0.5">
                      <button ref={focused ? activeDay : undefined} type="button" tabIndex={focused ? 0 : -1}
                        disabled={day.getFullYear() < 1 || day.getFullYear() > 9999}
                        aria-label={dayFormatter.format(day)} aria-current={key === todayKey ? "date" : undefined}
                        className={cn("flex h-8 w-full items-center justify-center rounded-full tabular-nums transition-colors hover:bg-muted motion-reduce:transition-none",
                          formControlFocusClassName,
                          day.getMonth() !== month.getMonth() && "text-muted-foreground/60",
                          key === todayKey && !selected && "font-semibold ring-1 ring-inset ring-border",
                          selected && "bg-foreground font-medium text-background hover:bg-foreground/90")}
                        onKeyDown={(event) => onDayKeyDown(event, day)} onClick={() => selectDay(day)}>
                        {day.getDate()}
                      </button>
                    </td>;
                  })}</tr>
                ))}</tbody>
              </table>
              <Button type="button" variant="ghost" size="sm" className="mt-2 w-full text-[12px]" onClick={() => selectDay(new Date())}>
                {t("settings.automations.calendar.today")}
              </Button>
            </PopoverContent>
          </Popover>
        </div>
        <div className="relative">
          <label htmlFor={`${id}-time`} className="sr-only">{t("settings.automations.fields.runTime")}</label>
          <Clock3 className="pointer-events-none absolute start-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden />
          <Input id={`${id}-time`} type="text" value={timeValue} placeholder="HH:mm"
            aria-describedby={errorId}
            aria-invalid={timeValue !== "" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(timeValue) || undefined}
            autoComplete="off" spellCheck={false} className="ps-9 text-[16px] tabular-nums sm:text-[13px]"
            onChange={(event) => onChange(`${dateValue}T${event.target.value}`)} />
        </div>
      </div>
    </fieldset>
  );
}
