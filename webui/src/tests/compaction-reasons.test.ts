import { describe, expect, it } from "vitest";

import { decodeNotification } from "../../../packages/client-events/notifications";
import { parseWebuiThreadPayload } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";

const base = { event: "context_compaction", chat_id: "chat", compaction_id: "compact",
  turn_id: "turn", turn_phase: "activity", turn_seq: 2, created_at_ms: 123 };

function history(events: unknown[]) {
  return projectThreadEvents(parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events }).events);
}

describe("compaction reason wire to history projection", () => {
  it.each(["idle", "context_pressure", "manual", "provider_native"] as const)(
    "preserves explicit %s through phase updates and rehydration", (reason) => {
      const start = { ...base, phase: "started", reason };
      const finish = { ...base, phase: "succeeded", reason, turn_seq: 3, created_at_ms: 456 };
      expect(decodeNotification(start)).toEqual(start);
      const rows = history([start, finish]);
      expect(rows).toHaveLength(1);
      expect(rows[0]).toMatchObject({ id: "compaction-compact", createdAt: 123,
        turnId: "turn", turnPhase: "activity", turnSeq: 3,
        compaction: { id: "compact", phase: "succeeded", reason } });
      expect(rows[0].compaction?.announce).toBeUndefined();
      expect(history(JSON.parse(JSON.stringify([start, finish])))).toEqual(rows);
      expect(history([{ ...finish, reason }])[0].compaction).toMatchObject({ reason, phase: "succeeded" });
    },
  );

  it("keeps old records neutral and rejects malformed reasons at the history boundary", () => {
    expect(history([{ ...base, phase: "succeeded" }])[0].compaction?.reason).toBeUndefined();
    for (const reason of ["unknown", null, 42]) {
      expect(() => history([{ ...base, phase: "succeeded", reason }])).toThrow("Invalid WebUI thread projection event");
    }
  });
});
