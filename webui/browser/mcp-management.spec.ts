import { expect, test } from "@playwright/test";

for (const width of [390, 1100]) {
  test(`MCP body opens management without connecting at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 850 });
    await page.goto("/browser/fixture.html?case=apps&oauth");
    const actions = page.getByTestId("mcp-actions");
    const body = page.getByRole("button", { name: "Design MCP", exact: true });
    await body.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Design MCP", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await expect(actions).toHaveText("[]");
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await page.getByRole("button", { name: "Connect Design MCP" }).click();
    await expect(dialog.getByRole("tab", { name: "Connection", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(actions).toHaveText("[]");
    await dialog.getByText("Advanced options", { exact: true }).click();
    const name = dialog.getByRole("textbox", { name: "OAuth client name", exact: true });
    await expect(name).toHaveValue("nanobot");
    await name.fill("Design assistant");
    await expect(actions).toHaveText("[]");
    await dialog.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(actions).toHaveText(JSON.stringify([{
      action: "oauth", name: "design", reset: false,
      values: { oauth_client_name: "Design assistant", use_proxy: "false" },
    }]));
  });
}

test("an existing OAuth name can be reset explicitly through reauthorization", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=apps&oauth&configured");
  await page.getByRole("button", { name: "Design MCP", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Design MCP", exact: true });
  await dialog.getByRole("tab", { name: "Connection", exact: true }).click();
  await dialog.getByText("Advanced options", { exact: true }).click();
  const name = dialog.getByRole("textbox", { name: "OAuth client name", exact: true });
  await expect(name).toHaveValue("Workspace client");
  await name.fill("");
  await expect(page.getByTestId("mcp-actions")).toHaveText("[]");
  await dialog.getByRole("button", { name: "Save and reauthorize", exact: true }).click();
  await expect(page.getByTestId("mcp-actions")).toHaveText(JSON.stringify([{
    action: "oauth", name: "design", reset: true,
    values: { oauth_client_name: "", use_proxy: "false" },
  }]));
});
