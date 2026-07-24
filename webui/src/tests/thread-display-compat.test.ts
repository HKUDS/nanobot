import { describe, expect, it } from "vitest";

import { deriveTitle, isModelCommandText, visibleSessionPreview } from "@/lib/format";
import {
  normalizeLegacyLongTaskMessages,
  projectWebuiThreadMessages,
} from "@/lib/thread-display-compat";
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

  it("removes model and silent-command turns without hiding concurrent replies", () => {
    const message = (
      id: string,
      role: UIMessage["role"],
      content: string,
      turnId?: string,
    ): UIMessage => ({ id, role, content, createdAt: 1, turnId });
    const visible = projectWebuiThreadMessages([
      message("model", "user", "/model fast", "model-turn"),
      message("model-reply", "assistant", "Switched model preset to fast.", "model-turn"),
      message("silent", "user", "/restart", "webui-system:restart"),
      message("reply", "assistant", "This unrelated reply stays visible.", "other-turn"),
    ]);

    expect(visible.map(({ content }) => content)).toEqual([
      "This unrelated reply stays visible.",
    ]);
    expect([
      isModelCommandText("/MODEL@nanobot fast"),
      isModelCommandText("/modelish"),
    ]).toEqual([true, false]);
    expect(visibleSessionPreview("Switched model preset to `fast`.")).toBe("");
    expect(deriveTitle("## Model\n- Current model: `gpt-5.5`", "New chat")).toBe("New chat");
  });
});
