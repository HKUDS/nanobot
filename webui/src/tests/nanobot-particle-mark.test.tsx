import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NanobotParticleMark } from "@/components/NanobotParticleMark";

function stubViewport(compact: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: compact && query === "(max-width: 639px)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NanobotParticleMark", () => {
  it("uses the desktop particle profile on wider viewports", () => {
    stubViewport(false);

    render(<NanobotParticleMark theme="dark" />);

    const mark = screen.getByTestId("nanobot-particle-mark");
    expect(mark).toHaveAttribute(
      "data-particle-profile",
      "desktop",
    );
    expect(mark.querySelector("img")).toBeNull();
    expect(
      existsSync(resolve(process.cwd(), "public", "brand", "nanobot_mark.svg")),
    ).toBe(true);
  });

  it("uses the compact particle profile on mobile viewports", () => {
    stubViewport(true);

    render(<NanobotParticleMark theme="light" />);

    expect(screen.getByTestId("nanobot-particle-mark")).toHaveAttribute(
      "data-particle-profile",
      "compact",
    );
  });
});
