import { expect, test } from "@playwright/test";

for (const width of [412, 1440]) {
  test.describe(`${width}px document startup skeleton`, () => {
    test.use({ viewport: { width, height: 922 }, reducedMotion: "reduce" });
    for (const surface of ["skills", "apps", "channels", "automations", "settings", "chat"]) {
      test(`${surface} paints before the application and stylesheet download`, async ({ page }) => {
        await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
        // Neither React nor the app stylesheet may supply this first paint.
        await page.route(/\/(?:src\/main\.tsx|assets\/index-[^/]+\.(?:js|css))$/, (route) => route.abort());
        await page.goto(`/#/${surface === "chat" ? "chat/websocket%3Aexample" : surface}`, { waitUntil: "domcontentloaded" });
        const shell = page.locator(".startup-shell");
        await expect(shell).toHaveAttribute("data-startup-surface", surface);
        await expect(shell).toHaveAttribute("aria-busy", "true");
        await expect(shell.locator(surface === "chat" ? ".startup-composer" : ".startup-page")).toBeVisible();
        const blocks = shell.locator(".startup-block:visible");
        expect(await blocks.count()).toBeGreaterThan(5);
        const box = await blocks.first().boundingBox();
        expect(box!.width).toBeGreaterThan(0);
        expect(box!.height).toBeGreaterThan(0);
        expect(await blocks.first().evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
        expect(await shell.getByRole("button").count()).toBe(0);
        expect(await shell.getByRole("textbox").count()).toBe(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
        const status = shell.getByRole("status");
        await expect(status).toHaveText("Loading nanobot…");
        expect(await status.evaluate((element) => element.getBoundingClientRect().width)).toBe(1);
      });
    }

    test("restores a collapsed sidebar and the settings-section alias before React", async ({ page }) => {
      await page.addInitScript(() => {
        localStorage.setItem("nanobot-webui.sidebar", "0");
        localStorage.setItem("nanobot-webui.theme", "dark");
        localStorage.setItem("nanobot.locale", "zh-CN");
      });
      await page.route("**/src/main.tsx", (route) => route.abort());
      await page.goto("/#/settings?section=skills");
      const shell = page.locator(".startup-shell");
      await expect(shell).toHaveAttribute("data-startup-surface", "skills");
      await expect(shell).toHaveAttribute("data-sidebar-expanded", "false");
      await expect(shell.getByRole("status")).toHaveText("正在加载 nanobot…");
      await expect(page.locator("html")).toHaveClass(/dark/);
      if (width === 1440) expect((await shell.locator(".startup-navigation").boundingBox())!.width).toBe(56);
    });
  });
}
