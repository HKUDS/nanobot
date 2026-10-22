import { expect, test, type Locator } from "@playwright/test";

const cases = [
  { name: "phone", width: 390, height: 844, touch: true, extra: "" },
  { name: "reported viewport", width: 946, height: 936, touch: false, extra: "" },
  { name: "desktop", width: 1440, height: 936, touch: false, extra: "" },
  { name: "sidebar rail", width: 1440, height: 936, touch: false, extra: "&collapsed" },
  { name: "custom sidebar", width: 1440, height: 936, touch: false, extra: "&sidebarWidth=384" },
  { name: "compact desktop composer", width: 1024, height: 936, touch: false, extra: "&sidebarWidth=480" },
  { name: "wide desktop", width: 1920, height: 1080, touch: false, extra: "" },
];

async function box(locator: Locator) {
  await expect(locator).toBeVisible();
  return (await locator.boundingBox())!;
}

function sameBox(actual: Awaited<ReturnType<typeof box>>, expected: typeof actual) {
  for (const key of ["x", "y", "width", "height"] as const) {
    // The live thread camera can retain its 1px scroll anchor after initial focus.
    expect(Math.abs(actual[key] - expected[key]), key).toBeLessThanOrEqual(1);
  }
}

for (const c of cases) for (const locale of ["en", "zh-CN"]) {
  test.describe(`${c.name} ${locale} new chat`, () => {
    test.use({ viewport: { width: c.width, height: c.height }, hasTouch: c.touch, reducedMotion: "reduce" });
    test("aligns the document skeleton with the real welcome, composer and header", async ({ page }) => {
      await page.addInitScript((language) => {
        Math.random = () => 0;
        localStorage.setItem("nanobot.locale", language);
      }, locale);
      await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
      const url = `/browser/fixture.html?case=new-chat-skeleton${c.extra}${locale === "zh-CN" ? "&dark" : ""}`;
      await page.goto(url);
      await expect(page.locator(".thread-composer-surface")).toBeVisible();
      await page.evaluate(async () => { await document.fonts.ready; });
      const loaded = {
        header: await box(page.getByTestId("thread-header")),
        controls: await page.getByTestId("thread-header").locator("button:visible").evaluateAll((elements) => elements.map((e) => {
          const { x, y, width, height } = e.getBoundingClientRect();
          return { x, y, width, height };
        })),
        composer: await box(page.locator(".thread-composer-surface")),
        input: await box(page.locator(".thread-composer-input")),
        footer: await box(page.locator(".thread-composer-footer")),
        greeting: await box(page.getByTestId("hero-greeting")),
        workspaceRow: await page.locator(".thread-composer-workspace-row").isVisible()
          ? await box(page.locator(".thread-composer-workspace-row")) : null,
      };
      await page.goto(`${url}&loading`);
      sameBox(await box(page.locator(".startup-chat-header")), loaded.header);
      sameBox(await box(page.locator(".startup-composer-surface")), loaded.composer);
      sameBox(await box(page.locator(".startup-composer-input")), loaded.input);
      sameBox(await box(page.locator(".startup-composer-footer")), loaded.footer);
      if (loaded.workspaceRow) sameBox(await box(page.locator(".startup-workspace-row")), loaded.workspaceRow);
      const controls = page.locator(".startup-header-menu:visible, .startup-header-actions > div");
      await expect(controls).toHaveCount(loaded.controls.length);
      for (let i = 0; i < loaded.controls.length; i++) sameBox(await box(controls.nth(i)), loaded.controls[i]);
      const greeting = await box(page.locator(".startup-welcome-line"));
      if (c.width < 640) expect(Math.abs(greeting.y + greeting.height / 2 - loaded.greeting.y - loaded.greeting.height / 2)).toBeLessThanOrEqual(1);
      else expect(Math.abs(greeting.y + greeting.height - loaded.greeting.y - loaded.greeting.height)).toBeLessThanOrEqual(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await expect(page.getByRole("status")).toHaveText("Loading nanobot…");
    });
  });
}
