import { expect, test, type Locator, type Page } from "@playwright/test";

async function disableGoalPropertyRegistration(page: Page) {
  await page.route("**/goal-island.css", async route => {
    const response = await route.fetch();
    const source = await response.text();
    const declarations = source.match(/@property --goal-island-/g) ?? [];
    expect(declarations).toHaveLength(3);
    await route.fulfill({ response, body: source.replaceAll("@property --goal-island-", "@unknown --goal-island-") });
  });
}

async function expectBackgroundToCover(page: Page, owner: Locator) {
  const surface = owner.locator(":scope > .goal-island-surface");
  const [ownerBox, surfaceBox, background] = await Promise.all([
    owner.boundingBox(),
    surface.boundingBox(),
    surface.evaluate(el => {
      const style = getComputedStyle(el, "::before");
      return { color: style.backgroundColor, radius: style.borderRadius };
    }),
  ]);
  expect(ownerBox).not.toBeNull();
  expect(surfaceBox).not.toBeNull();
  expect(surfaceBox!.width).toBeCloseTo(ownerBox!.width, 1);
  expect(surfaceBox!.height).toBeCloseTo(ownerBox!.height, 1);
  expect(background.color).not.toBe("rgba(0, 0, 0, 0)");
  expect(background.radius).not.toBe("0px");

  const image = await page.screenshot({ clip: { x: ownerBox!.x + 12, y: ownerBox!.y + 10, width: 1, height: 1 } });
  const pixel = await page.evaluate(async bytes => {
    const bitmap = await createImageBitmap(new Blob([new Uint8Array(bytes)], { type: "image/png" }));
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.drawImage(bitmap, 0, 0);
    return Array.from(context.getImageData(0, 0, 1, 1).data);
  }, Array.from(image));
  expect(pixel.slice(0, 3).every(channel => channel > 180)).toBe(true);
}

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`goal background covers the content without registered properties (${reducedMotion})`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion });
    await page.addInitScript(() => { localStorage.setItem("nanobot.locale", "en"); });
    await disableGoalPropertyRegistration(page);
    await page.goto("/browser/fixture.html?case=session-transition&preview&topic=goal");
    await page.addStyleTag({ content: '[data-testid="thread-header"] { background: black !important; }' });

    const trigger = page.getByRole("button", { name: "Show full goal" });
    await expect(trigger).toBeVisible();
    await page.locator(".goal-island").evaluate(async el => { await Promise.all(el.getAnimations().map(animation => animation.finished)); });
    await expectBackgroundToCover(page, trigger);

    await trigger.click();
    const panel = page.getByRole("dialog", { name: "Goal", exact: true });
    await expect(panel).toBeVisible();
    await panel.evaluate(async el => { await Promise.all(el.getAnimations({ subtree: true }).map(animation => animation.finished)); });
    await expectBackgroundToCover(page, panel);

    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expectBackgroundToCover(page, trigger);
  });
}
