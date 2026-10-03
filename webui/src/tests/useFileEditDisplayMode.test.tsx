import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useFileEditDisplayMode } from "@/hooks/useFileEditDisplayMode";
import {
  DEFAULT_LOCAL_PREFS,
  LOCAL_PREFS_STORAGE_KEY,
  writeLocalPreferences,
} from "@/lib/local-preferences";

function DisplayModeProbe() {
  const mode = useFileEditDisplayMode();
  return <div data-testid="mode">{mode}</div>;
}

describe("useFileEditDisplayMode", () => {
  afterEach(() => {
    localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
  });

  it("updates when local preferences change in the same document", async () => {
    render(<DisplayModeProbe />);

    expect(screen.getByTestId("mode")).toHaveTextContent("summary");

    act(() => {
      writeLocalPreferences({
        ...DEFAULT_LOCAL_PREFS,
        fileEditDisplayMode: "diff",
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("mode")).toHaveTextContent("diff");
    });
  });
});
