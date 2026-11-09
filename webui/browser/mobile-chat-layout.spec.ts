import { expect, test, type Page } from "@playwright/test";

async function recordBottomButtonFrames(page: Page) {
  await page.evaluate(() => {
    (window as unknown as { bottomButtonFrames: boolean[] }).bottomButtonFrames = [];
    let start = 0;
    const sample = () => {
      (window as unknown as { bottomButtonFrames: boolean[] }).bottomButtonFrames.push(
        Boolean(document.querySelector('button[aria-label="Scroll to bottom"]')),
      );
      if (performance.now() - start < 300) requestAnimationFrame(sample);
    };
    document.querySelector('button[aria-label="Scroll to bottom"]')!.addEventListener("click", () => {
      start = performance.now();
      requestAnimationFrame(sample);
    }, { once: true });
  });
}

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
      await expect(details.getByRole("progressbar", { name: "Context" })).toHaveAttribute("aria-valuenow", "22");
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

test("bottom button stays hidden throughout smooth navigation", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/**", route => route.fulfill({ json: {} }));
  await page.goto("/browser/fixture.html?case=mobile-chat-layout&project");
  const scroller = page.locator(".thread-message-viewport");
  const button = page.getByRole("button", { name: "Scroll to bottom" });
  await expect.poll(() => scroller.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(100);
  await expect(button).toBeHidden();
  const readableDistance = () => scroller.evaluate(el => {
    const rows = [...el.querySelectorAll<HTMLElement>(".thread-message-row")];
    const row = rows.reverse().find(item => item.getBoundingClientRect().height > 0)!;
    const gap = el.querySelector<HTMLElement>(".thread-message-end-gap")!;
    return row.getBoundingClientRect().bottom - (el.getBoundingClientRect().bottom - gap.getBoundingClientRect().height);
  });
  expect(await readableDistance()).toBeLessThanOrEqual(1);
  await scroller.hover();
  await page.mouse.wheel(0, -120);
  await expect(button).toBeVisible();
  expect(await readableDistance()).toBeGreaterThan(0);
  await expect(button).toBeVisible();
  await recordBottomButtonFrames(page);
  await button.click();
  await expect(button).toBeHidden();
  await expect.poll(() => scroller.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(1);
  await page.waitForTimeout(320);
  const frames = await page.evaluate(() => (window as unknown as { bottomButtonFrames: boolean[] }).bottomButtonFrames);
  expect(frames.length).toBeGreaterThan(1);
  expect(frames).not.toContain(true);
  await expect(button).toBeHidden();
});

test("bottom button stays hidden after focus scrolls a following thread", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/sessions/**", route => route.fulfill({ json: { prompts: [] } }));
  await page.goto("/browser/fixture.html?case=rail&workbench=1&focus-links=1");
  const scroller = page.locator(".thread-message-viewport");
  const links = scroller.locator("a");
  const button = page.getByRole("button", { name: "Scroll to bottom" });
  await expect(links).toHaveCount(45);
  await expect.poll(() => scroller.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(1);
  await expect(button).toBeHidden();

  const index = await scroller.evaluate(el => {
    const top = el.getBoundingClientRect().top;
    return [...el.querySelectorAll("a")].findIndex(link => {
      const offset = link.getBoundingClientRect().top - top;
      return offset > 48 && offset < 100;
    });
  });
  expect(index).toBeGreaterThan(0);
  await links.nth(index).focus();
  const initialTop = await scroller.evaluate(el => el.scrollTop);
  await page.keyboard.press("Shift+Tab");
  await expect(links.nth(index - 1)).toBeFocused();
  await expect(button).toBeVisible();
  const distance = initialTop - await scroller.evaluate(el => el.scrollTop);
  expect(distance).toBeGreaterThan(0);
  expect(distance).toBeLessThan(48);

  await recordBottomButtonFrames(page);
  await button.click();
  await expect.poll(() => scroller.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(1);
  await page.waitForTimeout(320);
  const frames = await page.evaluate(() => (window as unknown as { bottomButtonFrames: boolean[] }).bottomButtonFrames);
  expect(frames.length).toBeGreaterThan(1);
  expect(frames).not.toContain(true);
  await expect(button).toBeHidden();
});
