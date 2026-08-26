import i18n, { currentLocale } from "@/i18n";

/** Compact token counts for dense runtime metadata (for example, 74.9K). */
export function formatCompactTokenCount(value: number): string {
  if (value < 1_000) return Math.round(value).toLocaleString();
  if (value < 1_000_000) {
    const digits = value < 100_000 ? 1 : 0;
    return `${Number((value / 1_000).toFixed(digits))}K`;
  }
  const digits = value < 100_000_000 ? 1 : 0;
  return `${Number((value / 1_000_000).toFixed(digits))}M`;
}

const LOW_INFORMATION_TITLE_PREVIEWS = new Set([
  "hi",
  "hello",
  "hey",
  "hello nano",
  "hello nanobot",
  "hi nano",
  "hi nanobot",
  "你好",
  "您好",
  "嗨",
  "哈喽",
  "哈啰",
  "在吗",
]);

export function isModelCommandText(text: string | null | undefined): boolean {
  return /^\/model(?:@[A-Za-z0-9_]+)?(?:\s|$)/i.test(text?.trim() ?? "");
}

export function isModelCommandResponseText(text: string | null | undefined): boolean {
  const normalized = text?.trim() ?? "";
  return (
    /^## Model\s+- Current (?:model|selection error):/.test(normalized)
    || normalized.startsWith("Switched model preset to ")
    || normalized.startsWith("Could not switch model preset:")
    || normalized === "Usage: `/model [preset]`"
  );
}

export function visibleSessionPreview(preview: string | null | undefined): string {
  const normalized = preview?.trim() ?? "";
  return isModelCommandText(normalized) || isModelCommandResponseText(normalized) ? "" : normalized;
}

function isLowInformationTitlePreview(text: string): boolean {
  const normalized = text.toLowerCase().replace(/[.!?。！？~～\s]+$/g, "").trim();
  return (
    normalized.startsWith("/") ||
    LOW_INFORMATION_TITLE_PREVIEWS.has(normalized)
  );
}

/** Truncate the first user message into a chat title. */
export function deriveTitle(preview: string | undefined, fallback: string): string {
  if (!preview) return fallback;
  const oneLine = visibleSessionPreview(preview).replace(/\s+/g, " ").trim();
  if (!oneLine) return fallback;
  if (isLowInformationTitlePreview(oneLine)) return fallback;
  return oneLine.length > 60 ? `${oneLine.slice(0, 57)}…` : oneLine;
}

/** Loose ISO-or-epoch parser; returns ``null`` for missing/invalid input. */
function parseDate(value: string | number | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const RELATIVE_THRESHOLDS: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, "second"],
  [60, "minute"],
  [24, "hour"],
  [7, "day"],
  [4.345, "week"],
  [12, "month"],
  [Number.POSITIVE_INFINITY, "year"],
];

const relativeTimeFormatters = new Map<string, Intl.RelativeTimeFormat>();
const dateTimeFormatters = new Map<string, Intl.DateTimeFormat>();
const clockTimeFormatters = new Map<string, Intl.DateTimeFormat>();

function activeLocale(locale?: string): string {
  return locale || i18n.resolvedLanguage || i18n.language || currentLocale();
}

function relativeTimeFormatter(locale: string): Intl.RelativeTimeFormat {
  const existing = relativeTimeFormatters.get(locale);
  if (existing) return existing;
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  relativeTimeFormatters.set(locale, formatter);
  return formatter;
}

function dateTimeFormatter(locale: string): Intl.DateTimeFormat {
  const existing = dateTimeFormatters.get(locale);
  if (existing) return existing;
  const formatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  dateTimeFormatters.set(locale, formatter);
  return formatter;
}

function clockTimeFormatter(locale: string): Intl.DateTimeFormat {
  const existing = clockTimeFormatters.get(locale);
  if (existing) return existing;
  const formatter = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
  });
  clockTimeFormatters.set(locale, formatter);
  return formatter;
}

function isSameLocalCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
  );
}

export function relativeTime(
  value: string | number | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  if (!date) return "";
  let delta = (date.getTime() - Date.now()) / 1000;
  const formatter = relativeTimeFormatter(activeLocale(locale));
  for (const [step, unit] of RELATIVE_THRESHOLDS) {
    if (Math.abs(delta) < step) {
      return formatter.format(Math.round(delta), unit);
    }
    delta /= step;
  }
  return formatter.format(Math.round(delta), "year");
}

export function fmtDateTime(
  value: string | number | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  return date ? dateTimeFormatter(activeLocale(locale)).format(date) : "";
}

/**
 * Format a completion timestamp in the browser's local timezone.
 * Today's messages stay compact; older messages include their date for orientation.
 */
export function formatMessageEndTime(
  value: number | null | undefined,
  locale?: string,
): string {
  const date = parseDate(value);
  if (!date) return "";
  const loc = activeLocale(locale);
  return isSameLocalCalendarDay(date, new Date())
    ? clockTimeFormatter(loc).format(date)
    : dateTimeFormatter(loc).format(date);
}

/** Human-readable turn duration (wall-clock), locale-aware via ``Intl`` (seconds/minutes). */
export function formatTurnLatency(ms: number, locale?: string): string {
  const loc = activeLocale(locale);
  const msClamped = Math.max(0, ms);
  const secTotal = msClamped / 1000;
  if (secTotal < 60) {
    return new Intl.NumberFormat(loc, {
      style: "unit",
      unit: "second",
      unitDisplay: "narrow",
      maximumFractionDigits: secTotal < 10 ? 1 : 0,
      minimumFractionDigits: 0,
    }).format(secTotal);
  }
  const wholeMin = Math.floor(secTotal / 60);
  const remSec = Math.max(0, Math.round(secTotal - wholeMin * 60));
  const minStr = new Intl.NumberFormat(loc, {
    style: "unit",
    unit: "minute",
    unitDisplay: "narrow",
  }).format(wholeMin);
  const secStr = new Intl.NumberFormat(loc, {
    style: "unit",
    unit: "second",
    unitDisplay: "narrow",
    maximumFractionDigits: 0,
  }).format(remSec);
  return `${minStr}\u00a0${secStr}`;
}
