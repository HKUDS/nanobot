import type { UsageDetails, UsageRange } from "@/lib/types";

export function usageDetails(range: UsageRange = "30"): UsageDetails {
  const count = range === "retained" ? 400 : Number(range);
  const start = new Date("2026-09-22T00:00:00Z");
  start.setUTCDate(start.getUTCDate() - count + 1);
  const empty = {
    input_tokens: 0, output_tokens: 0, total_tokens: 0, cache_read_tokens: 0,
    cache_write_tokens: 0, cache_read_observed_input_tokens: 0,
    cache_write_observed_input_tokens: 0, reported_tokens: 0, estimated_tokens: 0,
    requests: 0, reported_requests: 0, estimated_requests: 0, successful_requests: 0,
    failed_requests: 0, generation_ms: 0, measured_output_tokens: 0, ttft_ms: 0,
    timed_requests: 0, duration_ms: 0,
  };
  const measured = { ...empty, input_tokens: 90, output_tokens: 10, total_tokens: 100,
    cache_read_tokens: 30, cache_read_observed_input_tokens: 60, reported_tokens: 100,
    requests: 1, reported_requests: 1, successful_requests: 1 };
  const failed = { ...empty, requests: 1, failed_requests: 1 };
  return {
    start_date: start.toISOString().slice(0, 10), end_date: "2026-09-22", timezone: "Asia/Shanghai",
    days: [{ date: "2026-09-21", ...failed }, { date: "2026-09-22", ...measured }],
    totals: { ...measured, requests: 2, failed_requests: 1 },
    models: [{ provider: "demo", model: "primary", ...failed }, { provider: "demo", model: "backup", ...measured }],
    other_models: empty,
    model_days: [{ date: "2026-09-22", provider: "demo", model: "backup", total_tokens: 100 }],
    active_days: 2, current_streak_days: 2, longest_streak_days: 2,
    coverage: { first_call_at_ms: Date.parse("2026-09-21T02:00:00Z"), last_call_at_ms: Date.parse("2026-09-22T02:00:00Z"), retained_requests: 2, max_days: 400, max_requests: 100000 },
  };
}
