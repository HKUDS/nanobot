import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TokenUsageCard } from "@/components/settings/TokenUsageCard";
import { TokenUsageModelTrend } from "@/components/settings/TokenUsageModelTrend";
import type { SettingsPayload } from "@/lib/types";

type Usage = NonNullable<SettingsPayload["usage"]>;
function day(date: string, tokens: number): Usage["days"][number] {
  return { date, total_tokens: tokens, input_tokens: tokens, output_tokens: 0,
    cache_read_tokens: 0, cache_write_tokens: 0, cache_read_observed_input_tokens: 0,
    cache_write_observed_input_tokens: 0, requests: 1 };
}
function usage(days: Usage["days"]): Usage {
  return { days, total_tokens: 999999, total_tokens_30d: 999999, total_tokens_365d: 1_500_000,
    peak_day_tokens: 999999, current_streak_days: 0, longest_streak_days: 0,
    active_days_30d: 0, requests_30d: 0, updated_at: "2026-09-09T00:00:00Z" };
}

describe("Token usage card", () => {
  it("uses the same plot box for stacked bars and the zero baseline, with dates outside", () => {
    const days = Array.from({ length: 30 }, (_, index) => {
      const date = `2026-09-${String(index + 1).padStart(2, "0")}`;
      return { date, usage: day(date, index === 0 ? 30_000_000 : index === 1 ? 1 : 0) };
    });
    const { container } = render(<TokenUsageModelTrend days={days} modelDays={[
      { date: days[0].date, provider: "openai", model: "a", total_tokens: 20_000_000 },
      { date: days[0].date, provider: "xai", model: "b", total_tokens: 10_000_000 },
      { date: days[1].date, provider: "openai", model: "a", total_tokens: 1 },
    ]} />);
    const plot = container.querySelector("[data-model-usage-plot]")!;
    const bars = within(screen.getByRole("group", { name: "Model trends" })).getAllByRole("img");
    expect(plot).toContainElement(bars[0]);
    const baseline = container.querySelector<HTMLElement>('[data-model-usage-gridline="2"]')!;
    expect(plot).toContainElement(baseline);
    expect(baseline.parentElement).toHaveStyle({ top: "100%" });
    expect(plot).not.toContainElement(screen.getByText("Sep 1"));
    expect(bars[0].firstElementChild).toHaveStyle({ height: "100%" });
    expect(bars[0].firstElementChild?.children).toHaveLength(2);
    expect(bars[1].firstElementChild).toHaveStyle({ height: `${1 / 30_000_000 * 100}%` });
    expect(bars[2].children).toHaveLength(0);
  });
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-09T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("uses one 30-day window for the total, chart and source percentages", () => {
    const today = { ...day("2026-09-09", 300), input_tokens: 240, output_tokens: 60, cache_read_tokens: 120, cache_read_observed_input_tokens: 180, cache_miss_tokens: 60, cache_unknown_tokens: 60, estimated_tokens: 100,
      sources: { user: day("2026-09-09", 200) } };
    render(<TokenUsageCard timeZone="UTC" usage={usage([
      day("2026-08-10", 9000), day("2026-08-11", 100), today, day("2026-09-10", 9000),
    ])} />);
    expect(screen.getByLabelText("400 tokens in the last 30 days")).toBeInTheDocument();
    const bars = within(screen.getByRole("group", { name: "Daily tokens" })).getAllByRole("img");
    expect(bars).toHaveLength(30);
    expect(bars.filter((bar) => bar.tabIndex === 0)).toEqual([bars[0], bars[29]]);
    expect(bars[0]).toHaveAccessibleName(/2026-08-11: 100 tokens, 1 requests/);
    expect(bars[29]).toHaveAccessibleName(/Cached input: 120, Cache write: 0, Cache miss: 60, Unknown status: 60, Output: 60/);
    const segments = bars[29].firstElementChild?.children;
    expect(segments).toHaveLength(4);
    expect(segments?.[0]).toHaveStyle({ height: "40%" });
    expect(segments?.[1]).toHaveStyle({ height: "20%" });
    expect(segments?.[2]).toHaveStyle({ height: "20%" });
    expect(segments?.[3]).toHaveStyle({ height: "20%" });
    expect(bars[0]).toHaveAccessibleName(/Cache miss: 0, Unknown status: 100/);
    expect(screen.getAllByText("50%")).toHaveLength(2);
    expect(screen.getByText("Unclassified")).toBeInTheDocument();
    expect(screen.getByText("13.3")).toBeInTheDocument();
    expect(screen.getByText(/Sep 9/)).toBeInTheDocument();
  });

  it.each([0, 100])("partitions cache writes without overlap when cached input is %i", (read) => {
    const output = read === 0 ? 20 : 40;
    const total = read + 100 + output;
    const today = { ...day("2026-09-09", total), input_tokens: read + 100, output_tokens: output,
      cache_read_tokens: read, cache_write_tokens: 100,
      cache_read_observed_input_tokens: read, cache_write_observed_input_tokens: read + 100,
      cache_miss_tokens: 0, cache_unknown_tokens: 0 };
    render(<TokenUsageCard usage={usage([today])} />);
    const bar = within(screen.getByRole("group", { name: "Daily tokens" })).getAllByRole("img")[29];
    expect(bar).toHaveAccessibleName(new RegExp(`Cached input: ${read}, Cache write: 100, Cache miss: 0, Unknown status: 0, Output: ${output}`));
    const segments = Array.from(bar.firstElementChild!.children);
    const values = [read, 100, output].filter(value => value > 0);
    expect(segments).toHaveLength(values.length);
    segments.forEach((segment, index) => expect(segment).toHaveStyle({ height: `${values[index] / total * 100}%` }));
  });

  it("keeps the read-only breakdown for older backends without per-call partitions", () => {
    render(<TokenUsageCard usage={usage([{ ...day("2026-09-09", 240), input_tokens: 200, output_tokens: 40,
      cache_read_tokens: 100, cache_write_tokens: 100,
      cache_read_observed_input_tokens: 100, cache_write_observed_input_tokens: 200 }])} />);
    const bar = within(screen.getByRole("group", { name: "Daily tokens" })).getAllByRole("img")[29];
    expect(bar).toHaveAccessibleName(/Cached input: 100, Cache write: 0, Cache miss: 0, Unknown status: 100, Output: 40/);
    expect(bar.firstElementChild?.children).toHaveLength(3);
    expect(bar.firstElementChild?.children[1]).toHaveStyle({ height: `${100 / 240 * 100}%` });
  });

  it("hides a legend entry when that segment stays empty across the window", () => {
    const today = { ...day("2026-09-09", 1000), cache_read_tokens: 200, cache_read_observed_input_tokens: 400 };
    const { rerender } = render(<TokenUsageCard usage={usage([today])} />);
    expect(screen.getByText("Cached input")).toBeInTheDocument();
    expect(screen.queryByText("Cache write")).not.toBeInTheDocument();
    rerender(<TokenUsageCard usage={usage([{ ...today, cache_write_tokens: 150, cache_write_observed_input_tokens: 400, cache_miss_tokens: 50, cache_unknown_tokens: 600 }])} />);
    expect(screen.getByText("Cache write")).toBeInTheDocument();
  });

  it("shows an empty state for zero usage", () => {
    render(<TokenUsageCard usage={usage([])} />);
    expect(screen.getByRole("status")).toHaveTextContent("No token usage in the last 30 days.");
  });

  it("flags the share of tokens that were estimated locally", () => {
    render(<TokenUsageCard usage={usage([{ ...day("2026-09-09", 1000), estimated_tokens: 250 }])} />);
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    const details = screen.getByRole("dialog", { name: "Token usage" });
    expect(within(details).getByText("25% of tokens are estimated")).toBeInTheDocument();
  });

  it("does not misrepresent unavailable usage as zero", () => {
    render(<TokenUsageCard />);
    expect(screen.getByRole("status")).toHaveTextContent("Usage data is unavailable.");
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("merges one model recorded under a provider prefix and a bare id", () => {
    const days = Array.from({ length: 30 }, (_, index) => {
      const date = new Date("2026-09-09T00:00:00Z");
      date.setUTCDate(date.getUTCDate() - 29 + index);
      const key = date.toISOString().slice(0, 10);
      return { date: key, usage: day(key, index === 29 ? 1000 : 0) };
    });
    render(<TokenUsageModelTrend days={days} models={[
      { ...day("2026-09-09", 600), provider: "openai_codex", model: "openai-codex/gpt-6",
        cache_read_tokens: 100, cache_read_observed_input_tokens: 200,
        reported_tokens: 600, estimated_tokens: 0, successful_requests: 1, failed_requests: 0,
        reported_requests: 1, estimated_requests: 0, generation_ms: 0, measured_output_tokens: 0,
        ttft_ms: 0, timed_requests: 0, duration_ms: 0 },
      { ...day("2026-09-09", 400), provider: "openai_codex", model: "gpt-6",
        cache_read_tokens: 50, cache_read_observed_input_tokens: 100,
        reported_tokens: 400, estimated_tokens: 0, successful_requests: 1, failed_requests: 0,
        reported_requests: 1, estimated_requests: 0, generation_ms: 0, measured_output_tokens: 0,
        ttft_ms: 0, timed_requests: 0, duration_ms: 0 },
    ]} modelDays={[
      { date: "2026-09-09", provider: "openai_codex", model: "openai-codex/gpt-6", total_tokens: 600 },
      { date: "2026-09-09", provider: "openai_codex", model: "gpt-6", total_tokens: 400 },
    ]} />);
    expect(screen.getAllByText("gpt-6")).toHaveLength(1);
    expect(screen.getByLabelText("gpt-6: Total tokens: 1,000 (100%), Cache hit rate: 50%")).toBeInTheDocument();
  });

  it("reports per-model speed, first-token wait and cache hit rate where measured", () => {
    const days = Array.from({ length: 30 }, (_, index) => {
      const date = new Date("2026-09-09T00:00:00Z");
      date.setUTCDate(date.getUTCDate() - 29 + index);
      const key = date.toISOString().slice(0, 10);
      return { date: key, usage: day(key, index === 29 ? 1500 : 0) };
    });
    render(<TokenUsageModelTrend days={days} modelDays={[
      { date: "2026-09-09", provider: "openai", model: "fast", total_tokens: 1000, measured_output_tokens: 400, generation_ms: 8000, ttft_ms: 3200, timed_requests: 1, cache_read_tokens: 700, cache_read_observed_input_tokens: 1000 },
      { date: "2026-09-09", provider: "openai", model: "legacy", total_tokens: 500 },
    ]} />);
    const column = screen.getAllByRole("img")[29];
    const label = column.getAttribute("aria-label") ?? "";
    expect(label).toContain("fast: 1,000, 50 tok/s, 3.2s to first token, 70% cache hit");
    expect(label).toContain("legacy: 500, Other models");
  });

  it("keeps the five leading model series and reconciles the rest to the daily total", () => {
    const days = Array.from({ length: 30 }, (_, index) => {
      const date = new Date("2026-09-09T00:00:00Z");
      date.setUTCDate(date.getUTCDate() - 29 + index);
      const key = date.toISOString().slice(0, 10);
      return { date: key, usage: day(key, index === 29 ? 2200 : 0) };
    });
    render(<TokenUsageModelTrend days={days}
      models={[{ ...day("2026-09-09", 600), provider: "provider", model: "model-5",
        cache_read_tokens: 120, cache_read_observed_input_tokens: 150,
        reported_tokens: 600, estimated_tokens: 0, successful_requests: 1, failed_requests: 0,
        reported_requests: 1, estimated_requests: 0, generation_ms: 0, measured_output_tokens: 0,
        ttft_ms: 0, timed_requests: 0, duration_ms: 0 }]}
      modelDays={Array.from({ length: 6 }, (_, index) => ({ date: "2026-09-09", provider: "provider", model: `model-${index}`, total_tokens: (index + 1) * 100 }))} />);
    const column = screen.getAllByRole("img")[29];
    expect(screen.getAllByRole("img").filter((bar) => bar.tabIndex === 0)).toEqual([column]);
    expect(column).toHaveAccessibleName(/2026-09-09: 2,200 tokens/);
    expect(column).toHaveAccessibleName(/model-5: 600/);
    expect(column).toHaveAccessibleName(/Other models: 200/);
    const legend = screen.getByLabelText("model-5: Total tokens: 600 (27.3%), Cache hit rate: 80%");
    expect(legend).toHaveAttribute("tabindex", "0");
  });
});
