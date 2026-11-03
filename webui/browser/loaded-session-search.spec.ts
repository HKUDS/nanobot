import { expect, test } from "@playwright/test";

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`selects a loaded body match from the search dialog at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/browser/fixture.html?case=loaded-session-search");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Search", exact: true });
    const input = dialog.getByRole("textbox", { name: "Search", exact: true });
    await input.fill("权限");
    await expect(dialog.getByRole("button")).toHaveCount(1);
    await expect(dialog.getByText("Topic 1", { exact: true })).toBeVisible();
    await expect(dialog.getByText("我们讨论权限与配对")).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    await dialog.screenshot({ path: test.info().outputPath(`loaded-search-${viewport.width}.png`) });
    await input.press("Enter");
    await expect(dialog).not.toBeVisible();
    await expect(page.getByLabel("Selected topic")).toHaveText("websocket:topic-1");
    expect(errors).toEqual([]);
  });
}
