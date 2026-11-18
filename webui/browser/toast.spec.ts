import { expect, test, type Locator } from "@playwright/test";

const fixture = "/browser/fixture.html?case=toast&lang=en&scene=";
const shadowStyle = (card: Locator, property: string) => card.evaluate(
  (element, key) => getComputedStyle(element, "::before").getPropertyValue(key),
  property,
);

test("plain feedback expires in the short tier while the pending delete stays available", async ({ page }) => {
  await page.clock.install();
  await page.goto(`${fixture}stack`);
  await page.getByRole("button", { name: "Play timing" }).click();

  const copied = page.locator('[data-toast-tone="success"]');
  const deletion = page.locator('[data-toast-tone="pending"]');
  await expect(copied.getByRole("status")).toHaveText("Copied");
  await expect(deletion.getByText("Research notes")).toBeVisible();
  expect(await shadowStyle(copied, "animation-duration")).toBe("3s");
  expect(await shadowStyle(deletion, "animation-duration")).toBe("8s");
  await page.clock.runFor(2_000);
  await expect(copied).toBeVisible();
  await page.clock.runFor(1_001);
  await expect(copied).toHaveCount(0);
  await deletion.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByText("Undo applied")).toBeVisible();
  await page.clock.runFor(8_001);
  await expect(page.getByText("Simulated delete committed")).toHaveCount(0);
});

test("a long title is clipped on one line without crowding keyboard undo on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 650 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  await page.goto(`${fixture}delete&dark&long-title`);
  await page.getByRole("button", { name: "Play timing" }).click();

  const card = page.locator('[data-toast-tone="pending"]');
  const status = card.getByRole("status");
  const undo = card.getByRole("button", { name: "Undo" });
  await expect(status).toContainText("Research notes: cross-platform layout and keyboard accessibility verification");
  await expect(undo).toBeInViewport();
  const bounds = (await card.boundingBox())!;
  const content = (await status.boundingBox())!;
  const button = (await undo.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(12);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(308);
  expect(bounds.height).toBeLessThanOrEqual(44);
  expect(button.x).toBeGreaterThan(content.x + content.width);
  expect(content.y + content.height / 2).toBeCloseTo(button.y + button.height / 2);
  expect(await status.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);

  await undo.focus();
  await expect(undo).toBeFocused();
  await page.clock.runFor(8_001);
  await undo.press("Enter");
  await expect(page.getByText("Undo applied")).toBeVisible();
});

test("a pending delete waits while hovered and commits after leaving the card", async ({ page }) => {
  await page.clock.install();
  await page.goto(`${fixture}delete`);
  await page.getByRole("button", { name: "Play timing" }).click();

  const undo = page.getByRole("button", { name: "Undo" });
  const committed = page.getByText("Simulated delete committed");
  const card = page.locator('[data-toast-tone="pending"]');
  await undo.hover();
  await expect.poll(() => shadowStyle(card, "animation-play-state")).toBe("paused");
  await page.clock.runFor(8_001);
  await expect(undo).toBeVisible();
  await expect(committed).toHaveCount(0);

  await page.getByRole("heading", { name: "Toast fixtures" }).hover();
  await expect.poll(() => shadowStyle(card, "animation-play-state")).toBe("running");
  await page.clock.runFor(8_001);
  await expect(committed).toBeVisible();
  await expect(undo).toHaveCount(0);
});

test("a modal sheet pauses an unreachable Undo and preserves the remaining time", async ({ page }) => {
  await page.clock.install();
  await page.goto(`${fixture}delete&modal`);
  await page.getByRole("button", { name: "Play timing" }).click();
  const undo = page.getByRole("button", { name: "Undo" });
  const card = page.locator('[data-toast-tone="pending"]');
  const committed = page.getByText("Simulated delete committed");
  await expect(undo).toBeVisible();
  await page.clock.runFor(3_000);
  await page.getByRole("button", { name: "Open sheet" }).click();
  await expect(page.getByRole("dialog", { name: "Navigation sheet" })).toBeVisible();
  await expect(undo).toHaveCount(0);
  await expect.poll(() => shadowStyle(card, "animation-play-state")).toBe("paused");
  await page.clock.runFor(8_001);
  await expect(card).toBeAttached();
  await expect(committed).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(undo).toBeVisible();
  await page.clock.runFor(4_000);
  await expect(undo).toBeVisible();
  await page.clock.runFor(1_100);
  await expect(committed).toBeVisible();
  await expect(undo).toHaveCount(0);
});
