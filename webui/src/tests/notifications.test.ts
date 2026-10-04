import { describe, expect, it } from "vitest";
import fixtures from "../../../packages/client-events/fixtures.json";
import { acceptsCompactionPhase, decodeNotification } from "../../../packages/client-events/notifications";

describe("shared notification contract", () => {
  it("rejects malformed retry counters and relative delays", () => {
    const retry = { event: "retry_status", chat_id: "chat", state: "waiting",
      attempt: 1, max_attempts: 4, error_kind: "connection", retry_after_s: 2 };
    for (const invalid of [
      { attempt: 0 }, { attempt: 1.5 }, { max_attempts: 0 }, { max_attempts: NaN },
      { retry_after_s: -1 }, { retry_after_s: Infinity }, { state: "unknown" },
    ]) expect(decodeNotification({ ...retry, ...invalid })).toBeNull();
  });
  it.each(fixtures)("accepts the Python wire fixture %#", (event) => {
    expect(decodeNotification(event)).toEqual(event);
    expect(decodeNotification({ ...event, turn_id: "turn" })).toMatchObject(event);
    expect(decodeNotification({ ...event, chat_id: 42 })).toBeNull();
    expect(decodeNotification({ ...event, turn_id: 42 })).toBeNull();
  });

  it("does not mistake other event families for invalid notifications", () => {
    expect(decodeNotification({ event: "delta", text: "hello" })).toBeUndefined();
    expect(decodeNotification({ ...fixtures[0], phase: "unknown" })).toBeNull();
    expect(decodeNotification({ ...fixtures[0], compaction_id: "" })).toBeNull();
  });

  it("allows one terminal transition, including terminal-first hydration", () => {
    for (const phase of ["started", "succeeded", "failed", "cancelled"] as const) {
      expect(acceptsCompactionPhase(undefined, phase)).toBe(true);
      expect(acceptsCompactionPhase("started", phase)).toBe(phase !== "started");
      for (const terminal of ["succeeded", "failed", "cancelled"] as const) {
        expect(acceptsCompactionPhase(terminal, phase)).toBe(false);
      }
    }
  });
});
