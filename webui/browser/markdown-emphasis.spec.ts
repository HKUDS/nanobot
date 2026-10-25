import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`CJK emphasis retains inline semantics through completion at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=markdown-emphasis");
    // Reveal the inline code while its enclosing emphasis is still incomplete.
    for (let index = 0; index < 24; index++) {
      await page.getByRole("button", { name: "Next character", exact: true }).click();
    }
    const reply = page.getByTestId("reply");
    await expect(reply.locator("code")).toHaveText("ThreadTranscript");
    await page.getByRole("button", { name: "Complete", exact: true }).click();
    await expect(reply.locator("strong code")).toHaveText("ThreadTranscript");
    await expect(reply.locator("strong a")).toHaveText("说明");
    await expect(reply.locator("strong a")).toHaveAttribute("href", "https://example.com");
    await expect(reply.locator("strong")).toHaveCount(7);
    await expect(reply.locator("p").last()).toHaveText("**边界说明： **issue");
    await expect(reply.locator("p").first()).toContainText("但“集中到一个类”不等于已经有清晰的状态机。");
    await expect(reply.locator("strong").first()).not.toContainText("但“集中到一个类”");
    await expect(reply).toBeVisible();
  });
}
