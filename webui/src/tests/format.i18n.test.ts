import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAppLanguage } from "@/i18n";
import {
  deriveTitle,
  fmtDateTime,
  formatTurnLatency,
  isModelCommandResponseText,
  isModelCommandText,
  relativeTime,
  visibleSessionPreview,
} from "@/lib/format";

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

  it("formats turn latency with locale-aware units", async () => {
    await setAppLanguage("en");
    const subMinute = formatTurnLatency(2400, "en");
    expect(subMinute).toBe(
      new Intl.NumberFormat("en", {
        style: "unit",
        unit: "second",
        unitDisplay: "narrow",
        maximumFractionDigits: 1,
        minimumFractionDigits: 0,
      }).format(2.4),
    );

    const minutePlus = formatTurnLatency(90_000, "en");
    expect(minutePlus).toContain("m");
    expect(minutePlus).toContain("s");
  });

  it("treats /model commands and their backend replies as hidden WebUI metadata", () => {
    expect(isModelCommandText("  /model fast  ")).toBe(true);
    expect(isModelCommandText("/MODEL@nanobot fast")).toBe(true);
    expect(isModelCommandText("/modelish")).toBe(false);
    expect(isModelCommandResponseText(
      "## Model\n- Current model: `gpt-5.5`",
    )).toBe(true);
    expect(isModelCommandResponseText(
      "Switched model preset to `fast`.\n- Scope: current session",
    )).toBe(true);
    expect(isModelCommandResponseText(
      "## Model\nA normal explanation of model behavior.",
    )).toBe(false);
    expect(visibleSessionPreview("/model fast")).toBe("");
    expect(visibleSessionPreview("Switched model preset to `fast`.")).toBe("");
    expect(deriveTitle("/model fast", "New chat")).toBe("New chat");
    expect(deriveTitle("A useful prompt", "New chat")).toBe("A useful prompt");
  });
});
