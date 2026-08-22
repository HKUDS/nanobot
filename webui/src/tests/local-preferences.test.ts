import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_LOCAL_PREFS,
  readLocalPreferences,
  writeLocalPreferences,
} from "@/lib/local-preferences";

describe("local preferences", () => {
  beforeEach(() => localStorage.clear());

  it("keeps browser notifications opt-in", () => {
    expect(DEFAULT_LOCAL_PREFS.browserNotifications).toBe(false);
    expect(readLocalPreferences().browserNotifications).toBe(false);

    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, browserNotifications: true });
    expect(readLocalPreferences().browserNotifications).toBe(true);
  });
});
