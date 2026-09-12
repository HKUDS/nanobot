import { expect, test } from "bun:test"
import { parseCodexQuota, quotaSummary } from "../../packages/client-events/operations"

test("quota windows use provider durations and preserve unknown reset", () => {
  const snapshot = parseCodexQuota({ enabled: true, state: "available", observed_at: 1000,
    gateway_account_matches: true, buckets: [{ limit_id: "codex", primary: {
      used_percent: 34, window_duration_mins: 10080, resets_at: null,
    }, secondary: null }] })
  expect(quotaSummary(snapshot)).toBe("Codex: 7d 34%")
  expect(snapshot.buckets[0]?.primary?.resets_at).toBeNull()
  expect(quotaSummary({ ...snapshot, state: "stale" })).toContain("nieaktualne")
  expect(quotaSummary({ ...snapshot, gateway_account_matches: false })).toContain("inne konto")
})

test("missing usage cannot silently become zero percent", () => {
  expect(() => parseCodexQuota({ enabled: true, state: "available", buckets: [
    { limit_id: "codex", primary: { window_duration_mins: 300 } },
  ] })).toThrow()
  expect(quotaSummary(parseCodexQuota({ enabled: true, state: "unavailable", buckets: [] }))).toBe("Codex: brak danych")
})
