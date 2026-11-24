import { fireEvent, render } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { McpActivityIcon } from "@/components/thread/activity/McpActivityIcon";
import { McpCatalogContext } from "@/hooks/useMcpPresetCatalog";
import { ThemeProvider } from "@/hooks/useTheme";
import { getToolsCatalog } from "@/lib/tools-catalog-cache";

it("selects a themed mark, skips failed URLs within a gateway, and retries on a later visit", () => {
  const first = getToolsCatalog({}, "token");
  const second = getToolsCatalog({}, "token");
  const neutral = "https://docs.example/neutral.png";
  const dark = "https://docs.example/dark.png";
  const view = (scope: typeof first) => <McpCatalogContext.Provider value={scope}><ThemeProvider theme="dark">
    <McpActivityIcon name="docs" icons={[{ src: neutral }, { src: dark, theme: "dark" }]} />
  </ThemeProvider></McpCatalogContext.Provider>;
  const row = render(view(first));
  const img = () => row.container.querySelector("img")!;
  expect(img()).toHaveAttribute("src", dark);
  fireEvent.error(img());
  expect(img()).toHaveAttribute("src", neutral);
  fireEvent.error(img());
  expect(row.container.querySelector('[data-product-icon="mcp"]')).toBeInTheDocument();
  row.rerender(view(second));
  expect(img()).toHaveAttribute("src", dark);
  row.rerender(view(first));
  expect(row.container.querySelector('[data-product-icon="mcp"]')).toBeInTheDocument();
  const clock = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 60_001);
  try {
    row.rerender(view(first));
    expect(img()).toHaveAttribute("src", dark);
  } finally {
    clock.mockRestore();
  }
});
