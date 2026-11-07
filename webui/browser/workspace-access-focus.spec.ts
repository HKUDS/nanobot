import { expect, test, type Locator, type Page } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
  await page.goto("/browser/fixture.html?case=new-chat-skeleton");
  await expect(page.locator(".thread-composer-access")).toBeVisible();
});

async function openWithKeyboard(page: Page, trigger: Locator) {
  await page.getByRole("textbox", { name: "Message input" }).click();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Attach files" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menuitemradio", { name: "Default Permission" })).toBeFocused();
}

async function expectPointerDismissal(page: Page, trigger: Locator) {
  await expect(page.getByRole("menu")).toHaveCount(0);
  // Observe the first closed-menu paint, after FocusScope's unmount restoration.
  await page.evaluate(() => new Promise(requestAnimationFrame));
  await expect(trigger).not.toBeFocused();
  expect(await trigger.evaluate(element => element.matches(":focus-visible"))).toBe(false);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
}

test("pointer selection does not refocus the trigger or reopen its tooltip", async ({ page }) => {
  const trigger = page.locator(".thread-composer-access");
  await trigger.click();
  await page.getByRole("menuitemradio", { name: "Default Permission" }).click();
  await expect(trigger).toHaveAccessibleName("Workspace access mode: Default Permission");
  await expectPointerDismissal(page, trigger);
});

test("keyboard selection restores visible focus to the permission trigger", async ({ page }) => {
  const trigger = page.locator(".thread-composer-access");
  await openWithKeyboard(page, trigger);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(trigger).toHaveAccessibleName("Workspace access mode: Default Permission");
  await expect(trigger).toBeFocused();
  expect(await trigger.evaluate(element => element.matches(":focus-visible"))).toBe(true);
});

test("Escape restores keyboard focus even after pointer entry", async ({ page }) => {
  const trigger = page.locator(".thread-composer-access");
  await trigger.click();
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(trigger).toHaveAccessibleName("Workspace access mode: Full Access");
  await expect(trigger).toBeFocused();
  expect(await trigger.evaluate(element => element.matches(":focus-visible"))).toBe(true);
});

test("pointer selection after keyboard entry does not restore keyboard focus", async ({ page }) => {
  const trigger = page.locator(".thread-composer-access");
  await openWithKeyboard(page, trigger);
  await page.getByRole("menuitemradio", { name: "Default Permission" }).click();
  await expectPointerDismissal(page, trigger);
});

test("pointer dismissal outside a keyboard-opened menu does not refocus the trigger", async ({ page }) => {
  const trigger = page.locator(".thread-composer-access");
  await openWithKeyboard(page, trigger);
  const greeting = (await page.getByTestId("hero-greeting").boundingBox())!;
  await page.mouse.click(greeting.x + 8, greeting.y + 8);
  await expectPointerDismissal(page, trigger);
});
