import { expect, test } from "@playwright/test";

test("About current-version feedback keeps its initial row height with wider system fonts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  const positions: number[] = [];
  for (const state of ["loaded", "loading"]) {
    await page.goto(`/browser/fixture.html?case=skeleton-additions&surface=settings&state=${state}&section=about`);
    await page.addStyleTag({ content: "body { font-family: monospace; }" });
    if (state === "loaded") await expect(page.getByText("You're up to date", { exact: true })).toBeVisible();
    const row = page.locator("[data-settings-section] .settings-list-row").first();
    await expect(row).toBeVisible();
    positions.push((await row.boundingBox())!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  }
  expect(Math.abs(positions[0] - positions[1])).toBeLessThan(0.5);
});

for (const state of ["loaded", "loading"]) {
  test(`About ${state} reserves the wordmark before its image loads`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    let release!: () => void;
    const pendingImage = new Promise<void>(resolve => { release = resolve; });
    await page.route("**/brand/nanobot_wordmark.svg", async route => {
      await pendingImage;
      await route.continue();
    });
    try {
      await page.goto(`/browser/fixture.html?case=skeleton-additions&surface=settings&state=${state}&section=about`, { waitUntil: "domcontentloaded" });
      const row = page.locator("[data-settings-section] .settings-list-row").first();
      await expect(row).toBeVisible();
      const before = await row.boundingBox();
      release();
      const wordmark = page.locator('img[alt="nanobot"]');
      await expect(wordmark).toHaveJSProperty("complete", true);
      expect(await wordmark.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      const after = await row.boundingBox();
      expect(Math.abs(after!.y - before!.y)).toBeLessThan(0.5);
    } finally {
      release();
    }
  });
}
