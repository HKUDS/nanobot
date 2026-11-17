import { expect, test } from "@playwright/test";

for (const width of [390, 1280]) {
  test(`current-chat model options preserve the compact preset menu at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=model-options");
    await page.getByRole("button", { name: "Default", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Switch model", exact: true });
    const selected = dialog.getByRole("option", { name: "default", exact: true });
    await expect(selected).toHaveAttribute("aria-selected", "true");
    await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
    const selectedBefore = await selected.boundingBox();
    const effort = dialog.getByRole("radiogroup", { name: "Reasoning effort" });
    const fast = dialog.getByRole("radiogroup", { name: "Codex Fast mode" });
    await expect(effort.getByRole("radio", { name: "Inherit", exact: true })).toBeChecked();
    await expect(fast.getByRole("radio", { name: "Inherit", exact: true })).toBeChecked();
    await effort.getByRole("radio", { name: "high", exact: true }).click();
    await fast.getByRole("radio", { name: "Off", exact: true }).click();
    await expect(page.getByLabel("Sent model options")).toHaveText("No model options sent");
    const selectedAfter = await selected.boundingBox();
    expect(selectedAfter?.height).toBe(selectedBefore?.height);
    expect(selectedAfter?.x).toBe(selectedBefore?.x);
    for (const group of [effort, fast]) {
      const bounds = (await group.boundingBox())!;
      expect(Math.abs(bounds.x - selectedAfter!.x)).toBeLessThan(1);
      expect(Math.abs(bounds.x + bounds.width - selectedAfter!.x - selectedAfter!.width)).toBeLessThan(1);
    }
    if (width === 390) {
      for (const radio of await dialog.getByRole("radio").all()) {
        expect((await radio.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      }
      expect(selectedBefore!.height).toBeGreaterThanOrEqual(44);
    }
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.mouse.move(0, 0);
    await dialog.evaluate((element) => Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished)));
    await page.screenshot({ path: `verification/NAN-355-model-options-${width}.png` });
    await dialog.press("Escape");
    await page.getByLabel("Message input").fill("Send with these options");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect(page.getByLabel("Sent model options")).toHaveText("Reasoning: high; Codex Fast: off");
    await page.reload();
    await page.getByRole("button", { name: "Default", exact: true }).click();
    await expect(effort.getByRole("radio", { name: "high", exact: true })).toBeChecked();
    await expect(fast.getByRole("radio", { name: "Off", exact: true })).toBeChecked();
    await dialog.getByRole("option", { name: "Review", exact: true }).click();
    await page.getByRole("button", { name: "Review", exact: true }).click();
    await expect(effort.getByRole("radio", { name: "Inherit", exact: true })).toBeChecked();
    await expect(fast.getByRole("radio", { name: "Inherit", exact: true })).toBeChecked();
    if (width === 1280) {
      await fast.getByRole("radio", { name: "On", exact: true }).hover();
      await expect(page.getByRole("tooltip")).toHaveText("Faster responses, increased usage.");
    }
  });
}

test("Temporary Chats do not expose model option controls", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=model-options&temporary");
  await page.getByRole("button", { name: "Default", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Switch model", exact: true })).toBeVisible();
  await expect(page.getByRole("radiogroup", { name: "Reasoning effort" })).toHaveCount(0);
  await expect(page.getByRole("radiogroup", { name: "Codex Fast mode" })).toHaveCount(0);
});
