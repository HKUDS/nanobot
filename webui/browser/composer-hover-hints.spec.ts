import { expect, test, type Locator } from "@playwright/test";

test.use({ reducedMotion: "reduce" });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
});

async function visibleHint(trigger: Locator) {
  await trigger.hover();
  const hint = trigger.page().locator("[data-radix-popper-content-wrapper] > [data-state]");
  await expect(hint).toBeVisible();
  await expect(hint).toHaveCSS("opacity", "1");
  return hint;
}

for (const scenario of [
  { name: "hero", width: 1280, url: "new-chat-skeleton" },
  { name: "narrow", width: 390, url: "mobile-chat-layout&project" },
  { name: "narrow pane", width: 1280, url: "workspace-alignment&containerWidth=360" },
]) {
  test(`${scenario.name} hints avoid the composer and stay within its column`, async ({ page }) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    await page.goto(`/browser/fixture.html?case=${scenario.url}`);
    const input = page.getByRole("textbox", { name: "Message input" });
    const trigger = page.locator(".thread-composer-access");
    for (const draft of ["Keep this draft visible.", "Keep this draft visible.\n".repeat(6)]) {
      await input.fill(draft);
      const hint = await visibleHint(trigger);
      const bounds = (await hint.boundingBox())!;
      const surface = (await page.locator(".thread-composer-surface").boundingBox())!;
      const column = (await page.locator(".thread-composer-form").boundingBox())!;
      const above = bounds.y + bounds.height <= surface.y - 7;
      const below = bounds.y >= column.y + column.height + 7;
      const beside = bounds.x + bounds.width <= surface.x - 7 || bounds.x >= surface.x + surface.width + 7;
      expect(above || below || beside).toBe(true);
      if (surface.y >= bounds.height + 16) expect(above).toBe(true);
      expect(bounds.x).toBeGreaterThanOrEqual(column.x + 7);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(column.x + column.width - 7);
      await input.hover();
      await expect(hint).not.toBeVisible();
    }
  });
}

test("editing and composition dismiss a hint until a fresh hover", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=new-chat-skeleton");
  const input = page.getByRole("textbox", { name: "Message input" });
  const trigger = page.locator(".thread-composer-access");
  await input.fill("Keep typing while the pointer is over permissions.");
  await trigger.hover();
  await page.keyboard.type(" During the hover delay.");
  await page.waitForTimeout(600);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await input.hover();
  let hint = await visibleHint(trigger);
  await page.keyboard.type(" More text.");
  await expect(hint).not.toBeVisible();
  // The pointer has not left the trigger; a dismissed hint must not revive.
  await page.waitForTimeout(600);
  await expect(hint).not.toBeVisible();
  await input.hover();
  hint = await visibleHint(trigger);
  await input.dispatchEvent("compositionstart", { data: "n" });
  await expect(hint).not.toBeVisible();
  await input.dispatchEvent("compositionend", { data: "你" });
  await input.hover();
  hint = await visibleHint(trigger);
  await page.keyboard.press("Escape");
  await expect(hint).not.toBeVisible();
  await trigger.focus();
  await expect(page.getByRole("tooltip")).toContainText("Allow file access");
});

test("a directory dialog's hints stay with the dialog, not its composer", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=workspace-alignment");
  await page.getByRole("button", { name: "Switch directory", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const editPath = dialog.getByRole("button", { name: /^Edit path:/ });
  const hint = await visibleHint(editPath);
  const bounds = (await hint.boundingBox())!;
  const trigger = (await editPath.boundingBox())!;
  expect(Math.abs(bounds.y + bounds.height - trigger.y)).toBeLessThan(8);
  await expect(dialog).toBeVisible();
});

test("a short viewport dismisses a hint rather than putting it over the draft", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/browser/fixture.html?case=workspace-alignment&containerWidth=360");
  await page.getByRole("textbox", { name: "Message input" }).fill("Keep this draft visible.\n".repeat(5));
  const trigger = page.locator(".thread-composer-access");
  const hint = await visibleHint(trigger);
  await page.setViewportSize({ width: 1280, height: 240 });
  await expect(trigger).toBeInViewport();
  await expect(hint).not.toBeVisible();
  await expect(trigger).toHaveAccessibleDescription("Allow file access and commands outside the working directory.");
});
