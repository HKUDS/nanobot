import { expect, test } from "@playwright/test";

for (const width of [390, 1280]) {
  test(`preset summary keeps its settings visible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/browser/fixture.html?case=skeleton-additions&surface=settings&state=loaded&section=models");

    const row = page.getByTestId("model-call-order-row-primary");
    const model = row.getByText("openai-codex/gpt-6.1-sol", { exact: true });
    const settings = row.getByText("500K max", { exact: true });
    await expect(model).toBeVisible();
    await expect(settings).toBeVisible();
    expect(await settings.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    if (width === 390) {
      expect(await model.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
      await model.hover();
      await expect(page.getByRole("tooltip")).toHaveText("openai-codex/gpt-6.1-sol");
    }
  });
}
