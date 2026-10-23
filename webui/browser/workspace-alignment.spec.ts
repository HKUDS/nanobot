import { expect, test } from "@playwright/test";

const cases = [
  { name: "desktop", width: 1280, touch: false, extra: "" },
  { name: "tablet", width: 1280, touch: true, extra: "" },
  { name: "small desktop", width: 600, touch: false, extra: "" },
  { name: "phone", width: 390, touch: true, extra: "" },
  { name: "narrow desktop pane", width: 1024, touch: false, extra: "&containerWidth=480" },
];

for (const variant of ["hero", "thread"]) for (const c of cases) {
  test.describe(`${variant} ${c.name}`, () => {
    test.use({ viewport: { width: c.width, height: 900 }, hasTouch: c.touch, reducedMotion: "reduce" });
    test("aligns the directory glyph with the attachment glyph", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
      await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
      await page.goto(`/browser/fixture.html?case=workspace-alignment&composerVariant=${variant}${c.extra}`);
      const attachment = page.getByRole("button", { name: "Attach files" }).locator("svg");
      const workspace = page.getByRole("button", { name: "Switch directory" }).locator('[data-product-icon="workspace"]');
      await expect(workspace).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const attachmentBox = (await attachment.boundingBox())!;
      const workspaceBox = (await workspace.boundingBox())!;
      expect(workspaceBox.x).toBeCloseTo(attachmentBox.x, 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    });
  });
}
