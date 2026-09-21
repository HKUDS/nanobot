import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { usePageVisibility } from "@/hooks/usePageVisibility";

describe("usePageVisibility", () => {
  it("tracks visibility changes so background work can pause and resume", () => {
    const original = Object.getOwnPropertyDescriptor(document, "visibilityState");
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });

    const { result, unmount } = renderHook(usePageVisibility);
    try {
      expect(result.current).toBe(false);

      act(() => {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "visible",
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(result.current).toBe(true);
    } finally {
      unmount();
      if (original) {
        Object.defineProperty(document, "visibilityState", original);
      } else {
        delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState;
      }
    }
  });
});
