import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`invitation follows the app theme without losing its artwork or layout at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto("/browser/fixture.html?case=theme-toggle&star");
    await page.getByRole("button", { name: "Open invitation", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const images = dialog.locator(".star-prompt-art img");
    await expect(images).toHaveCount(2);
    await expect.poll(() => images.evaluateAll(elements => elements.every(element => {
      const image = element as HTMLImageElement;
      return image.complete && image.naturalWidth === 1672 && image.naturalHeight === 941;
    }))).toBe(true);
    await expect(images.nth(0)).toHaveCSS("opacity", "1");
    await expect(images.nth(1)).toHaveCSS("opacity", "0");
    await expect(dialog).toHaveCSS("animation-name", "none");
    const initial = (await dialog.boundingBox())!;
    await page.screenshot({ path: info.outputPath("invitation-day.png") });

    // System changes are live even while the modal is open.
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(images.nth(0)).toHaveCSS("opacity", "0");
    await expect(images.nth(1)).toHaveCSS("opacity", "1");
    // Color can still fade; await its settled state rather than sampling the first paint.
    await expect(dialog).toHaveCSS("background-color", "rgb(36, 41, 50)");
    const night = (await dialog.boundingBox())!;
    expect(Math.abs(night.height - initial.height)).toBeLessThanOrEqual(1);
    expect(night.x).toBeGreaterThanOrEqual(0);
    expect(night.x + night.width).toBeLessThanOrEqual(width);
    await expect(dialog.getByRole("button", { name: "Maybe later" })).toBeInViewport();
    await page.screenshot({ path: info.outputPath("invitation-night.png") });

    // Explicit Light must override a dark OS, rather than using an image media query.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
    await page.getByRole("button", { name: "Open invitation", exact: true }).click();
    await expect(images.nth(0)).toHaveCSS("opacity", "1");
    await expect(images.nth(1)).toHaveCSS("opacity", "0");
    await dialog.getByRole("button", { name: "Maybe later" }).click();
    await expect(dialog).toBeHidden();
  });
}
