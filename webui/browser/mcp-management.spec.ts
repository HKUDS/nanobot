import { expect, test } from "@playwright/test";

for (const width of [390, 1100]) {
  test(`MCP body opens management without connecting at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 850 });
    await page.goto("/browser/fixture.html?case=apps&manage");
    const actions = page.getByTestId("mcp-actions");
    const body = page.getByRole("button", { name: "Design MCP", exact: true });
    const dialog = page.getByRole("dialog", { name: "Design MCP", exact: true });
    await body.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await expect(actions).toHaveText("[]");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await body.focus();
    await page.keyboard.press(width === 390 ? "Enter" : "Space");
    await expect(dialog).toBeVisible();
    await expect(actions).toHaveText("[]");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await page.getByRole("button", { name: "Connect Design MCP" }).click();
    await expect(dialog.getByRole("tab", { name: "Connection", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(actions).toHaveText("[]");
    await dialog.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(actions).toHaveText(JSON.stringify([{
      action: "oauth", name: "design", reset: false, values: { use_proxy: "false" },
    }]));
  });
}
