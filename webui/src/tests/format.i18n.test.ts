import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAppLanguage } from "@/i18n";
import { fmtDateTime, relativeTime } from "@/lib/format";

describe("localized format helpers", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-18T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats relative time using the active locale", async () => {
    const value = "2026-04-18T11:59:00Z";

    await setAppLanguage("en");
    const english = relativeTime(value);

    await setAppLanguage("zh-CN");
    const chinese = relativeTime(value);

    expect(english).toBe(
      new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(
        -1,
        "minute",
      ),
    );
    expect(chinese).toBe(
      new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" }).format(
        -1,
        "minute",
      ),
    );
    expect(english).not.toBe(chinese);
  });

  it("formats date-time using the active locale", async () => {
    const value = "2026-04-18T08:30:00Z";
    const date = new Date(value);

    await setAppLanguage("en");
    const english = fmtDateTime(value);

    await setAppLanguage("fr");
    const french = fmtDateTime(value);

    expect(english).toBe(
      new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date),
    );
    expect(french).toBe(
      new Intl.DateTimeFormat("fr", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date),
    );
    expect(english).not.toBe(french);
  });
});
