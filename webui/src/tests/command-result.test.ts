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

  it("keeps optional argument syntax on the same line as its translated help", () => {
    const entry = { prefix: "/model [preset] — ", key: "palette.model.description", values: {} };
    expect(renderCommandResult({ command: "/help", parts: [entry] }, "zh-TW"))
      .toBe("/model [preset] — 檢視或切換當前模型預設");
  });

  it("uses the same command spelling for the localized goal menu and the server", () => {
    expect(commandLabel("/cancel_goal", "title", "zh-CN")).toBe("取消目标");
  });
});
