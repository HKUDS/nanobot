import { describe, expect, it } from "vitest";
import { commandLabel, renderCommandResult } from "../../../packages/client-events/command-result";

describe("command receipts", () => {
  it("translates a saved result without interpreting model names or raw output", () => {
    const preset = "{preset} $&";
    const result = { command: "/model", parts: [
      { key: "model.switched", values: { preset } }, { text: preset },
    ] };
    expect(renderCommandResult(result, "zh-Hant")).toBe(`已切換為 \`${preset}\`。\n${preset}`);
    expect(renderCommandResult(result, "en")).toBe(`Switched model preset to \`${preset}\`.\n${preset}`);
  });

  it("uses the same command spelling for the localized goal menu and the server", () => {
    expect(commandLabel("/cancel_goal", "title", "zh-CN")).toBe("取消目标");
  });
});
