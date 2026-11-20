/**
 * Usage counters are routinely eight to eleven digits. Reading them requires
 * locale units (`100.5亿`, `10B`), but the exact value still has to stay
 * available for titles, accessible labels, and diagnostics.
 */
const COMPACT_THRESHOLD = 10_000;

export interface UsageNumberFormats {
  /** Locale units for five-digit and larger values, exact digits below that. */
  display: (value: number) => string;
  /** Grouped exact digits. */
  exact: (value: number) => string;
}

export interface UsageFormats extends UsageNumberFormats {
  /** Locale units regardless of magnitude. */
  compact: (value: number) => string;
  /** Percentage with one fraction digit. */
  percent: (value: number) => string;
  /** Milliseconds as seconds with one fraction digit. */
  seconds: (value: number) => string;
  /** Short month and day for a `YYYY-MM-DD` key, in UTC. */
  date: (date: string) => string;
}

const formatsByLocale = new Map<string, UsageFormats>();

/**
 * `Intl` constructors are comparatively expensive and the usage panels
 * re-render on every hover, so each locale's formatters are built once.
 */
export function usageFormats(locale: string): UsageFormats {
  const cached = formatsByLocale.get(locale);
  if (cached) return cached;
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  const exact = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 });
  const seconds = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const date = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", timeZone: "UTC" });
  const formats: UsageFormats = {
    display: (value) => (Math.abs(value) >= COMPACT_THRESHOLD ? compact.format(value) : exact.format(value)),
    exact: (value) => exact.format(value),
    compact: (value) => compact.format(value),
    percent: (value) => percent.format(value),
    seconds: (value) => seconds.format(value / 1000),
    date: (value) => date.format(new Date(`${value}T00:00:00Z`)),
  };
  formatsByLocale.set(locale, formats);
  return formats;
}

/** Output tokens per second, or `null` when no generation time was measured. */
export function usageSpeed(measuredOutputTokens: number, generationMs: number): number | null {
  return generationMs > 0 ? measuredOutputTokens / (generationMs / 1000) : null;
}
