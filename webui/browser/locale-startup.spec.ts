import { expect, test } from "@playwright/test";

test.use({ locale: "zh-CN" });

test("startup follows the browser without saving an automatic preference", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/src/main.tsx", async route => {
    await pending;
    await route.continue();
  });
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.locator("[data-boot-copy]")).toHaveText("正在加载 nanobot…");
    release();
    await expect(page.locator("[data-boot-copy]")).toHaveCount(0);
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    expect(await page.evaluate(() => localStorage.getItem("nanobot.locale"))).toBeNull();
    await page.reload();
    await expect(page.locator("[data-boot-copy]")).toHaveCount(0);
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    expect(await page.evaluate(() => localStorage.getItem("nanobot.locale"))).toBeNull();
  } finally {
    release();
  }
});
