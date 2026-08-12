import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_LOCAL_PREFS,
  LOCAL_PREFS_STORAGE_KEY,
  LOCAL_PREFS_VERSION,
  readLocalPreferences,
  writeLocalPreferences,
} from "@/lib/local-preferences";

describe("local preferences", () => {
  beforeEach(() => localStorage.clear());

  it("shows brand logos by default", () => {
    expect(DEFAULT_LOCAL_PREFS.brandLogos).toBe(true);
    expect(readLocalPreferences().brandLogos).toBe(true);
  });

  it("preserves an explicit brand-logo opt-out", () => {
    localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify({
      version: LOCAL_PREFS_VERSION,
      brandLogos: false,
    }));

    expect(readLocalPreferences().brandLogos).toBe(false);
  });

  it("migrates the old auto-persisted opt-out to visible logos", () => {
    localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify({ brandLogos: false }));

    expect(readLocalPreferences().brandLogos).toBe(true);
  });

  it("enables brand logos for legacy preferences without the field", () => {
    localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify({ density: "compact" }));

    expect(readLocalPreferences().brandLogos).toBe(true);
  });

  it("versions newly written preferences", () => {
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, brandLogos: false });

    expect(JSON.parse(localStorage.getItem(LOCAL_PREFS_STORAGE_KEY) ?? "{}")).toMatchObject({
      version: LOCAL_PREFS_VERSION,
      brandLogos: false,
    });
  });
});
