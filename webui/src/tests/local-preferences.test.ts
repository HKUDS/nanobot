import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_LOCAL_PREFS,
  LOCAL_PREFS_STORAGE_KEY,
  readLocalPreferences,
  writeLocalPreferences,
} from "@/lib/local-preferences";

describe("local preferences", () => {
  beforeEach(() => localStorage.clear());

  it("shows third-party brand logos by default while preserving an explicit opt-out", () => {
    expect(DEFAULT_LOCAL_PREFS.brandLogos).toBe(true);
    expect(readLocalPreferences().brandLogos).toBe(true);

    localStorage.setItem(
      LOCAL_PREFS_STORAGE_KEY,
      JSON.stringify({ brandLogos: false }),
    );
    expect(readLocalPreferences().brandLogos).toBe(false);
  });

  it("keeps browser notifications opt-in", () => {
    expect(DEFAULT_LOCAL_PREFS.browserNotifications).toBe(false);
    expect(readLocalPreferences().browserNotifications).toBe(false);

    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, browserNotifications: true });
    expect(readLocalPreferences().browserNotifications).toBe(true);
  });
});
