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

for (const variant of ["hero", "thread"]) for (const width of [280, 320, 390, 600, 1024, 1280]) {
  test.describe(`${variant} permission at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width < 640, reducedMotion: "reduce" });
    test("places mobile permission opposite the directory and preserves desktop placement", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
      await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
      await page.goto(`/browser/fixture.html?case=workspace-alignment&composerVariant=${variant}${width === 1024 ? "&containerWidth=480" : ""}`);
      const workspace = page.getByRole("button", { name: "Switch directory" });
      const access = page.getByRole("button", { name: "Workspace access mode: Full Access" });
      await expect(access).toBeVisible();
      const surface = (await page.locator(".thread-composer-surface").boundingBox())!;
      const accessBox = (await access.boundingBox())!;
      if (width < 640) {
        const workspaceBox = (await workspace.boundingBox())!;
        expect(accessBox.y).toBeGreaterThanOrEqual(surface.y + surface.height);
        expect(Math.abs(accessBox.y + accessBox.height / 2 - workspaceBox.y - workspaceBox.height / 2)).toBeLessThan(1);
        expect(accessBox.x).toBeGreaterThan(workspaceBox.x + workspaceBox.width);
        expect(surface.x + surface.width - accessBox.x - accessBox.width).toBeLessThan(16);
        expect(await access.evaluate(element => !!element.closest(".thread-composer-meta"))).toBe(true);
      } else {
        expect(accessBox.y + accessBox.height).toBeLessThanOrEqual(surface.y + surface.height);
        expect(await access.evaluate(element => !!element.closest(".thread-composer-footer-primary"))).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await access.click();
      await page.getByRole("menuitemradio", { name: "Default Permission" }).click();
      await expect(page.getByRole("button", { name: "Workspace access mode: Default Permission" })).toBeVisible();
    });
  });
}

for (const variant of ["hero", "thread"]) {
  test.describe(`${variant} mobile permission with usage`, () => {
    test.use({ viewport: { width: 320, height: 900 }, hasTouch: true, reducedMotion: "reduce" });
    test("keeps access on the lower right when context usage appears", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
      await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
      await page.goto(`/browser/fixture.html?case=workspace-alignment&composerVariant=${variant}&usage=1`);
      const workspace = (await page.getByRole("button", { name: "Switch directory" }).boundingBox())!;
      const access = (await page.getByRole("button", { name: "Workspace access mode: Full Access" }).boundingBox())!;
      const usage = (await page.getByTestId("composer-context-usage").boundingBox())!;
      expect(Math.abs(access.y - workspace.y)).toBeLessThan(1);
      expect(usage.y + usage.height).toBeLessThanOrEqual(access.y);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.getByTestId("composer-context-usage").focus();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Switch directory" })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Workspace access mode: Full Access" })).toBeFocused();
    });
  });
}

test.describe("permission across phone and desktop widths", () => {
  test.use({ viewport: { width: 390, height: 900 }, hasTouch: true, reducedMotion: "reduce" });
  test("keeps the draft and one usable permission trigger when the viewport changes", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
    await page.goto("/browser/fixture.html?case=workspace-alignment&composerVariant=hero");
    const input = page.getByRole("textbox", { name: "Message input" });
    await input.fill("keep this draft");
    for (const width of [1280, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(input).toHaveValue("keep this draft");
      const access = page.getByRole("button", { name: "Workspace access mode: Full Access" });
      await expect(access).toHaveCount(1);
      await expect.poll(() => access.evaluate((element, mobile) => !!element.closest(mobile ? ".thread-composer-meta" : ".thread-composer-footer-primary"), width < 640)).toBe(true);
    }
    await page.getByRole("button", { name: "Workspace access mode: Full Access" }).click();
    await expect(page.getByRole("menuitemradio", { name: "Default Permission" })).toBeVisible();
  });
});
