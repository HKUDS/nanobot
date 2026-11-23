import { describe, expect, it } from "vitest";
import { normalizeUsageModel } from "@/lib/usage-model";

describe("usage model names", () => {
  it("strips a prefix that repeats the provider", () => {
    expect(normalizeUsageModel("openai_codex", "openai-codex/gpt-6.1-sol")).toBe("gpt-6.1-sol");
    expect(normalizeUsageModel("openai_codex", "openai/gpt-6-astra")).toBe("gpt-6-astra");
    expect(normalizeUsageModel("custom-ffsa", "custom/model")).toBe("model");
  });

  it("keeps prefixes that belong to the model name", () => {
    expect(normalizeUsageModel("custom-ffsa", "qwen/qwen3.8-27b")).toBe("qwen/qwen3.8-27b");
    expect(normalizeUsageModel("zhipu", "glm-5.3-flash")).toBe("glm-5.3-flash");
    expect(normalizeUsageModel("openai_codex", "gpt-6-astra")).toBe("gpt-6-astra");
    expect(normalizeUsageModel("acme", "/leading-slash")).toBe("/leading-slash");
  });
});
