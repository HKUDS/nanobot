import { describe, expect, it } from "vitest";

import { normalizeLegacyLongTaskMessages } from "@/lib/thread-display-compat";
import type { UIMessage } from "@/lib/types";

describe("normalizeLegacyLongTaskMessages", () => {
  it("maps legacy long_task rows to trace lines", () => {
    const legacy = {
      id: "x",
      role: "assistant",
      kind: "long_task",
      content: "long_task · done",
      createdAt: 1,
    } as unknown as UIMessage;
    const out = normalizeLegacyLongTaskMessages([legacy]);
    expect(out[0]!.kind).toBe("trace");
    expect(out[0]!.role).toBe("tool");
    expect(out[0]!.traces).toEqual(["long_task · done"]);
  });
});
