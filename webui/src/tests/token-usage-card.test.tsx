import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TokenUsageCard } from "@/components/settings/TokenUsageCard";
import type { SettingsPayload } from "@/lib/types";

type Usage = NonNullable<SettingsPayload["usage"]>;
function day(date: string, tokens: number): Usage["days"][number] {
  return { date, total_tokens: tokens, input_tokens: tokens, output_tokens: 0,
    cache_read_tokens: 0, cache_write_tokens: 0, cache_read_observed_input_tokens: 0,
    cache_write_observed_input_tokens: 0, requests: 1 };
}
function usage(days: Usage["days"]): Usage {
  return { days, total_tokens: 999999, total_tokens_30d: 999999, total_tokens_365d: 999999,
    peak_day_tokens: 999999, current_streak_days: 0, longest_streak_days: 0,
    active_days_30d: 0, requests_30d: 0, updated_at: "2026-09-09T00:00:00Z" };
}

describe("Token usage card", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-09T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("uses one 30-day window for the total, chart and source percentages", () => {
    const today = { ...day("2026-09-09", 300), input_tokens: 240, output_tokens: 60, cache_read_tokens: 120, cache_read_observed_input_tokens: 180, estimated_tokens: 100,
      sources: { user: day("2026-09-09", 200) } };
    render(<TokenUsageCard timeZone="UTC" usage={usage([
      day("2026-08-10", 9000), day("2026-08-11", 100), today, day("2026-09-10", 9000),
    ])} />);
    expect(screen.getByLabelText("400 tokens")).toBeInTheDocument();
    const bars = within(screen.getByRole("group", { name: "Daily token usage" })).getAllByRole("img");
    expect(bars).toHaveLength(30);
    expect(bars[0]).toHaveAccessibleName(/2026-08-11: 100 tokens, 1 requests/);
    expect(bars[29]).toHaveAccessibleName(/Cached input: 120, Cache miss: 60, Cache unknown: 60, Output: 60/);
    const segments = bars[29].firstElementChild?.children;
    expect(segments).toHaveLength(4);
    expect(segments?.[0]).toHaveStyle({ height: "40%" });
    expect(segments?.[1]).toHaveStyle({ height: "20%" });
    expect(segments?.[2]).toHaveStyle({ height: "20%" });
    expect(segments?.[3]).toHaveStyle({ height: "20%" });
    expect(bars[0]).toHaveAccessibleName(/Cache miss: 0, Cache unknown: 100/);
    expect(screen.getAllByText("50%")).toHaveLength(2);
    expect(screen.getByText("Unclassified")).toBeInTheDocument();
    expect(screen.queryByText(/includes estimates/i)).not.toBeInTheDocument();
  });

  it("shows a quiet empty state without a chart for zero usage", () => {
    render(<TokenUsageCard usage={usage([])} />);
    expect(screen.getByRole("status")).toHaveTextContent("No token usage in the last 30 days.");
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("does not misrepresent unavailable usage as zero", () => {
    render(<TokenUsageCard />);
    expect(screen.getByRole("status")).toHaveTextContent("Usage data is unavailable.");
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
