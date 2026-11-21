import { describe, expect, it } from "vitest";
import { usageFormats } from "@/lib/usage-number";

describe("usage number formats", () => {
  it("switches to locale units once a count reaches five digits", () => {
    const en = usageFormats("en");
    const zh = usageFormats("zh-CN");
    expect(en.display(10_046_620_708)).toBe("10B");
    expect(en.display(69_134)).toBe("69.1K");
    expect(en.display(3039)).toBe("3,039");
    expect(zh.display(10_046_620_708)).toBe("100.5亿");
    expect(zh.display(10_324)).toBe("1万");
    expect(zh.display(3039)).toBe("3,039");
  });

  it("keeps exact digits for titles and accessible labels", () => {
    const en = usageFormats("en");
    expect(en.exact(10_046_620_708)).toBe("10,046,620,708");
    expect(en.exact(0)).toBe("0");
  });

  it("builds one formatter set per locale", () => {
    expect(usageFormats("en")).toBe(usageFormats("en"));
    expect(usageFormats("en")).not.toBe(usageFormats("zh-CN"));
    expect(usageFormats("en").percent(0.5)).toBe("50%");
    expect(usageFormats("en").date("2026-10-27")).toBe("Oct 27");
  });
});
