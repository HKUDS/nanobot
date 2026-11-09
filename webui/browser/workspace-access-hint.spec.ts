import { expect, test } from "@playwright/test";

test.use({ reducedMotion: "reduce" });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
});

for (const width of [1280, 390]) for (const variant of ["hero", "thread", "locked-thread"]) for (const permission of ["Full Access", "Default Permission"]) {
  test(`${variant} ${permission} hint avoids short and multiline drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/browser/fixture.html?case=${variant === "hero" ? "new-chat-skeleton" : variant === "thread" ? "mobile-chat-layout&project" : "mobile-chat-layout&no-context"}`);
    const input = page.getByRole("textbox", { name: "Message input" });
    const access = page.locator(".thread-composer-access");
    const hint = page.locator("[data-radix-popper-content-wrapper] > [data-state]");
    if (permission === "Default Permission") {
      await access.click();
      await page.getByRole("menuitemradio", { name: permission }).click();
    }
    for (const draft of ["Keep this draft visible.", "Keep this draft visible.\n".repeat(6)]) {
      await input.fill(draft);
      await access.hover();
      await expect(hint).toBeVisible();
      await expect(hint).toHaveCSS("opacity", "1");
      const bounds = (await hint.boundingBox())!;
      const editor = (await input.boundingBox())!;
      const trigger = (await access.boundingBox())!;
      expect(bounds.y >= editor.y + editor.height || bounds.y + bounds.height <= editor.y).toBe(true);
      expect(bounds.x).toBeGreaterThanOrEqual(0);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
      expect(bounds.y).toBeGreaterThanOrEqual(0);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(900);
      if (await hint.getAttribute("data-side") === "top") {
        const composer = (await page.locator(".thread-composer-form").boundingBox())!;
        expect(bounds.y + bounds.height).toBeLessThanOrEqual(composer.y - 7);
      }
      if (trigger.y + trigger.height + bounds.height + 16 <= 900) {
        expect(bounds.y).toBeGreaterThanOrEqual(trigger.y + trigger.height + 7);
      }
      await page.keyboard.press("Escape");
      await page.mouse.move(0, 0);
    }
  });
}


test("a visible permission hint stays above the composer as a locked-thread draft grows", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto("/browser/fixture.html?case=mobile-chat-layout&no-context");
  const input = page.getByRole("textbox", { name: "Message input" });
  const hint = page.locator("[data-radix-popper-content-wrapper] > [data-state]");
  await input.fill("Keep this draft visible.");
  await page.locator(".thread-composer-access").hover();
  await expect(hint).toBeVisible();
  await expect(hint).toHaveAttribute("data-side", "top");
  await page.keyboard.insertText("\nKeep this draft visible.".repeat(12));
  await expect(input).toHaveValue("Keep this draft visible." + "\nKeep this draft visible.".repeat(12));
  await expect.poll(async () => {
    const bounds = (await hint.boundingBox())!;
    const composer = (await page.locator(".thread-composer-form").boundingBox())!;
    return composer.y - bounds.y - bounds.height;
  }).toBeGreaterThanOrEqual(7);
  const bounds = (await hint.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(0);
});
