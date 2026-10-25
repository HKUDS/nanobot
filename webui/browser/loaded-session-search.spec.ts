import { expect, test } from "@playwright/test";

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`searches only loaded body text without requests at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const apiRequests: string[] = [];
    const errors: string[] = [];
    page.on("request", (request) => { if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url()); });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/browser/fixture.html?case=loaded-session-search");
    await page.getByRole("button", { name: "Search", exact: true }).waitFor();
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog", { name: "Search", exact: true });
    const input = dialog.getByRole("textbox", { name: "Search", exact: true });
    await expect(dialog.getByRole("button")).toHaveCount(24);
    for (const query of ["权限", "full access", "25%", "session_history.py"]) {
      await input.fill(query);
      await expect(dialog.getByRole("button")).toHaveCount(1);
      await expect(dialog.getByText("Topic 1", { exact: true })).toBeVisible();
      await expect(dialog.getByText(query === "权限" ? "我们讨论权限与配对" : /Use Full Access at 25%/)).toBeVisible();
    }
    await input.fill("unloaded server content");
    await expect(dialog.getByText("No matching topics.")).toBeVisible();
    await input.fill("权限");
    const box = await dialog.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    await dialog.screenshot({ path: test.info().outputPath(`loaded-search-${viewport.width}.png`) });
    await input.press("Enter");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByLabel("Selected topic")).toHaveText("websocket:topic-1");
    await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("Keep this unsent draft");
    expect(apiRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
}
