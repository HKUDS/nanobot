import { expect, test } from "@playwright/test";

for (const placement of ["center", "bottom"]) {
  test(`oversized ${placement} dialog keeps both ends keyboard-reachable`, async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 320 });
    await page.goto(`/browser/fixture.html?placement=${placement}`);
    const background = page.getByRole("main", { name: "Background content", includeHidden: true });
    const trigger = page.getByRole("button", { name: "Open tall dialog" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Tall dialog" });
    const close = dialog.getByRole("button", { name: "Close", exact: true });
    const lastAction = dialog.getByRole("button", { name: "Save tall dialog" });
    await expect(dialog.getByRole("heading", { name: "Tall dialog" })).toBeInViewport({ ratio: 1 });
    await expect(close).toBeInViewport({ ratio: 1 });
    expect(await dialog.evaluate((element) => element.scrollHeight)).toBeGreaterThan(320);
    await expect(page.locator("body")).toHaveAttribute("data-scroll-locked", "1");

    await close.focus();
    await page.keyboard.press("Shift+Tab");
    await expect(lastAction).toBeFocused();
    await expect(lastAction).toBeInViewport({ ratio: 1 });
    expect(await background.evaluate((element) => element.scrollTop)).toBe(0);
    await lastAction.press("Enter");
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await expect(page.locator("body")).not.toHaveAttribute("data-scroll-locked");
    await background.hover({ position: { x: 300, y: 180 } });
    await page.mouse.wheel(0, 400);
    await expect.poll(() => background.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  });
}

test("reopened completed history is readable without subtree entrance motion", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=history");
  const history = page.getByRole("region", { name: "Persisted history" });
  for (let reopen = 0; reopen < 2; reopen++) {
    const observation = await history.evaluateHandle((element) => {
      const names = new Set<string>();
      let frames = 0;
      let frame = 0;
      const onAnimation = (event: Event) => names.add((event as AnimationEvent).animationName);
      element.addEventListener("animationstart", onAnimation);
      const sample = () => {
        for (const animation of element.getAnimations({ subtree: true })) {
          names.add(animation.constructor.name);
        }
        frames++;
        frame = requestAnimationFrame(sample);
      };
      frame = requestAnimationFrame(sample);
      return {
        get frames() { return frames; },
        stop() {
          cancelAnimationFrame(frame);
          element.removeEventListener("animationstart", onAnimation);
          return [...names];
        },
      };
    });
    try {
      await page.getByRole("button", { name: "Reopen history" }).click();
      await expect(history.getByText("Earlier question", { exact: true })).toBeVisible();
      await expect(history.getByText("Earlier answer", { exact: true })).toBeVisible();
      await expect(history.getByRole("button", { name: "Using a tool", exact: true })).toBeVisible();
      await expect.poll(() => observation.evaluate((record) => record.frames)).toBeGreaterThan(12);
      expect(await observation.evaluate((record) => record.stop())).toEqual([]);
    } finally {
      await observation.evaluate((record) => record.stop());
      await observation.dispose();
    }
    const disclosure = history.getByRole("button", { name: "Using a tool", exact: true });
    await disclosure.click();
    await expect(history.getByText("Earlier tool call", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close history" }).click();
    await expect(history.getByText("Earlier question", { exact: true })).not.toBeVisible();
  }
});
