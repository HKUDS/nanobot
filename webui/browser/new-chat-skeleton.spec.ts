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
    test("aligns the document skeleton with the real composer and header", async ({ page }) => {
      await page.addInitScript((language) => {
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
        mark: await box(page.getByTestId("thread-welcome-mark")),
        input: await box(page.locator(".thread-composer-input")),
        footer: await box(page.locator(".thread-composer-footer")),
        workspaceRow: await box(page.locator(".thread-composer-meta")),
        workspaceControl: await box(page.locator(".thread-composer-workspace")),
      };
      await expect(page.getByTestId("thread-empty-region").getByRole("heading", {
        level: 1, name: locale === "en" ? "New topic" : "新建话题",
      })).toHaveClass("sr-only");
      await expect(page.getByTestId("thread-welcome-mark").locator(".thread-welcome-mark__focus")).toHaveCSS("mask-image", /nanobot_mark_outline\.svg/);
      await expect(page.getByTestId("thread-welcome-mark").locator(".thread-welcome-mark__fill")).toHaveCSS("background-image", /nanobot_mark\.svg/);
      await expect(page.getByTestId("thread-welcome-mark").locator(".thread-welcome-mark__fill")).toHaveCSS("filter", "grayscale(1)");
      expect(Math.abs(loaded.mark.x + loaded.mark.width / 2 - loaded.composer.x - loaded.composer.width / 2)).toBeLessThanOrEqual(1);
      expect(loaded.mark.y).toBeLessThan(loaded.composer.y);
      expect(loaded.mark.y + loaded.mark.height).toBeGreaterThan(loaded.composer.y);
      await expect(page.getByTestId("thread-welcome-mark")).toHaveCSS("pointer-events", "none");
      await page.goto(`${url}&loading`);
      sameBox(await box(page.locator(".startup-chat-header")), loaded.header);
      sameBox(await box(page.locator(".startup-composer-surface")), loaded.composer);
      sameBox(await box(page.locator(".startup-composer-input")), loaded.input);
      sameBox(await box(page.locator(".startup-composer-footer")), loaded.footer);
      sameBox(await box(page.locator(".startup-workspace-row")), loaded.workspaceRow);
      expect((await box(page.locator(".startup-workspace-row .startup-workspace"))).x).toBeCloseTo(loaded.workspaceControl.x, 1);
      const controls = page.locator(".startup-header-menu:visible, .startup-header-actions > div");
      await expect(controls).toHaveCount(loaded.controls.length);
      for (let i = 0; i < loaded.controls.length; i++) sameBox(await box(controls.nth(i)), loaded.controls[i]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await expect(page.getByRole("status")).toHaveText("Loading nanobot…");
    });
  });
}

test("keeps the welcome marks proportional and inside split panes as the window resizes", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 936 });
  await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
  await page.goto("/browser/fixture.html?case=new-chat-skeleton&split");
  const panes = page.locator(".workbench-pane");
  await expect(panes).toHaveCount(3);

  for (const width of [1100, 946]) {
    await page.setViewportSize({ width, height: 936 });
    for (const pane of await panes.all()) {
      const region = await box(pane.getByTestId("thread-empty-region"));
      const mark = await box(pane.getByTestId("thread-welcome-mark"));
      expect(mark.x).toBeGreaterThanOrEqual(region.x - 0.1);
      expect(mark.x + mark.width).toBeLessThanOrEqual(region.x + region.width + 0.1);
      expect(mark.width / mark.height).toBeCloseTo(783 / 742, 2);
    }
  }
});

test("draws the nose bridge and the original cheek lines", async ({ page }) => {
  await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
  await page.goto("/browser/fixture.html?case=new-chat-skeleton");
  await expect(page.getByTestId("thread-welcome-mark")).toBeVisible();
  const pixels = await page.evaluate(async () => {
    const image = new Image();
    image.src = "/brand/nanobot_mark_outline.svg";
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 783;
    canvas.height = 742;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    return [[379, 200], [379, 400], [379, 650], [80, 497], [680, 497]]
      .map(([x, y]) => context.getImageData(x + 12, y + 12, 1, 1).data[3]);
  });
  expect(pixels[0]).toBe(0);
  expect(pixels[1]).toBeGreaterThan(0);
  expect(pixels[2]).toBe(0);
  expect(pixels[3]).toBeGreaterThan(0);
  expect(pixels[4]).toBeGreaterThan(0);
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test.describe(`welcome mark with ${reducedMotion} motion`, () => {
    test.use({ reducedMotion });
    test("reveals the outline near the pointer and hides the focus when the window loses focus", async ({ page }) => {
      await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
      await page.goto("/browser/fixture.html?case=new-chat-skeleton");
      const mark = page.getByTestId("thread-welcome-mark");
      const bounds = await box(mark);
      const focus = mark.locator(".thread-welcome-mark__focus");
      const position = () => mark.evaluate((element) => ({
        x: Number.parseFloat(element.style.getPropertyValue("--mark-x")),
        y: Number.parseFloat(element.style.getPropertyValue("--mark-y")),
      }));

      await page.mouse.move(bounds.x + 40, bounds.y + 50);
      await expect.poll(async () => Math.abs((await position()).x - 40)).toBeLessThan(1);
      await expect(focus).toHaveCSS("opacity", "1");
      await page.mouse.move(bounds.x + bounds.width - 40, bounds.y + 70);
      await expect.poll(async () => Math.abs((await position()).x - (bounds.width - 40))).toBeLessThan(1);
      expect(Math.abs((await position()).y - 70)).toBeLessThan(1);

      await page.evaluate(() => window.dispatchEvent(new Event("blur")));
      await expect(focus).toHaveCSS("opacity", "0");
    });
  });
}
