import { expect, test } from "@playwright/test";

for (const { width, dark } of [{ width: 360, dark: false }, { width: 314, dark: true }, { width: 600, dark: false }]) {
  test.describe(`mobile transcript at ${width}px`, () => {
    test.use({ viewport: { width, height: 740 }, hasTouch: true, reducedMotion: "reduce" });
    test("keeps metadata tappable on one row and the top fade fixed while scrolling", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
      await page.route("**/api/**", route => route.fulfill({ json: {} }));
      await page.goto(`/browser/fixture.html?case=mobile-chat-layout&project&long-project${dark ? "&dark" : ""}`);
      const workspace = page.getByRole("button", { name: "Switch directory" });
      const usage = page.getByRole("button", { name: "Context 22%. Open context usage" });
      const access = page.getByRole("button", { name: "Workspace access mode: Full Access" });
      await expect(usage).toHaveText("22%");
      const boxes = await Promise.all([workspace, usage, access].map(control => control.boundingBox()));
      const [directoryBox, usageBox, accessBox] = boxes.map(box => box!);
      for (const box of boxes) {
        expect(box!.height).toBeGreaterThanOrEqual(44);
        expect(box!.width).toBeGreaterThanOrEqual(44);
        expect(box!.y).toBeCloseTo(accessBox.y, 1);
      }
      expect(directoryBox.x + directoryBox.width).toBeLessThanOrEqual(usageBox.x);
      expect(usageBox.x + usageBox.width).toBeLessThanOrEqual(accessBox.x);
      expect(accessBox.x + accessBox.width).toBeLessThanOrEqual(width);
      expect(740 - accessBox.y - accessBox.height).toBeCloseTo(8, 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);

      await usage.click();
      const details = page.getByRole("dialog", { name: "Context usage" });
      await expect(details.getByRole("progressbar", { name: "Context 22%" })).toHaveAttribute("aria-valuenow", "22");
      await page.keyboard.press("Escape");
      await expect(usage).toBeFocused();

      const scroller = page.locator(".thread-message-viewport");
      await expect(scroller).toHaveCSS("--thread-top-clearance", "6px");
      await expect(scroller).toHaveCSS("--thread-top-fade-height", "22px");
      const mask = await scroller.evaluate(node => getComputedStyle(node).maskImage);
      expect(mask).toContain("6px");
      expect(mask).toContain("22px");
      expect(mask).toContain("calc(100% - 36px)");
      await page.evaluate(() => document.fonts.ready);
      await expect.poll(() => scroller.evaluate(node => node.scrollHeight - node.clientHeight)).toBeGreaterThan(100);
      await expect.poll(() => scroller.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThanOrEqual(1);
      const before = (await scroller.boundingBox())!;
      const initialScrollTop = await scroller.evaluate(node => node.scrollTop);
      await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
      await page.mouse.wheel(0, -100);
      await expect.poll(() => scroller.evaluate(node => node.scrollTop)).toBeLessThan(initialScrollTop - 50);
      expect((await scroller.boundingBox())!.y).toBeCloseTo(before.y, 1);
      expect(await scroller.evaluate(node => getComputedStyle(node).maskImage)).toBe(mask);
    });
  });
}

test.describe("desktop transcript spacing", () => {
  test.use({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  test("preserves desktop footer spacing and the bottom-only fade", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.route("**/api/**", route => route.fulfill({ json: {} }));
    await page.goto("/browser/fixture.html?case=mobile-chat-layout&project");
    const access = page.getByRole("button", { name: "Workspace access mode: Full Access" });
    await expect(access).toBeVisible();
    expect(await access.evaluate(node => !!node.closest(".thread-composer-footer-primary"))).toBe(true);
    const meta = (await page.locator(".thread-composer-meta").boundingBox())!;
    expect(900 - meta.y - meta.height).toBeCloseTo(18, 1);
    const scroller = page.locator(".thread-message-viewport");
    await expect(scroller).toHaveCSS("--thread-top-clearance", "0px");
    await expect(scroller).toHaveCSS("--thread-top-fade-height", "0px");
    expect(await scroller.evaluate(node => getComputedStyle(node).maskImage)).toContain("calc(100% - 36px)");
  });
});
