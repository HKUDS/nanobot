/**
 * Shared chrome for the two usage charts: the peak/average axis and the date
 * axis below the bars. Both charts draw 30 columns over the same window, so
 * they must not drift apart in scale, ticks, or labels.
 */

export interface UsageAxisTick {
  value: number;
  top: number;
  /** Stable identity for `data-*-gridline`, independent of which ticks render. */
  gridline: 0 | 1 | 2;
}

/** Peak at the top, daily average as the reference line, zero as the baseline. */
export function usageAxisTicks(peak: number, average: number): UsageAxisTick[] {
  if (peak <= 0) return [];
  const meanTop = Math.min(100, (1 - average / peak) * 100);
  const ticks: UsageAxisTick[] = [{ value: peak, top: 0, gridline: 0 }];
  // A mean hugging the peak would print two labels on top of each other.
  if (meanTop >= 12) ticks.push({ value: average, top: meanTop, gridline: 1 });
  ticks.push({ value: 0, top: 100, gridline: 2 });
  return ticks;
}

/** Horizontal center of the peak column, in percent of the plot width. */
export function usagePeakCenter(columns: number, peakIndex: number): number {
  return columns ? ((peakIndex + 0.5) / columns) * 100 : 0;
}

export function UsageAxis({ ticks, format, gridlineAttribute }: {
  ticks: UsageAxisTick[];
  format: (value: number) => string;
  gridlineAttribute: "data-usage-gridline" | "data-model-usage-gridline";
}) {
  return (
    <div className="pointer-events-none absolute inset-y-0 -left-11 right-0" aria-hidden>
      {ticks.map(tick => (
        <div key={tick.gridline} className="absolute inset-x-0 flex items-center gap-2" style={{ top: `${tick.top}%` }}>
          {tick.value > 0 && <span className="absolute top-0 w-9 -translate-y-1/2 whitespace-nowrap text-right text-[10px] tabular-nums text-muted-foreground">{format(tick.value)}</span>}
          <span className="ml-11 flex-1 border-t border-border/40" {...{ [gridlineAttribute]: tick.gridline }} />
        </div>
      ))}
    </div>
  );
}

export function UsageDateAxis({ start, peak, end, peakCenter, format }: {
  start: string;
  peak: string;
  end: string;
  peakCenter: number;
  format: (date: string) => string;
}) {
  // Keep the peak label inside the plot instead of letting it hang off an edge.
  const peakStyle = peakCenter < 17
    ? { left: 0 }
    : peakCenter > 83
      ? { left: "100%", transform: "translateX(-100%)" }
      : { left: `${peakCenter}%`, transform: "translateX(-50%)" };
  return (
    <div className="relative mt-2 h-4 text-[10px] tabular-nums text-muted-foreground" aria-hidden>
      {peakCenter > 20 && <span className="absolute left-0 top-0">{format(start)}</span>}
      {peakCenter < 80 && <span className="absolute right-0 top-0">{format(end)}</span>}
      <span className="absolute top-0 whitespace-nowrap text-orange-500 dark:text-orange-400" style={peakStyle}>{format(peak)}</span>
    </div>
  );
}
