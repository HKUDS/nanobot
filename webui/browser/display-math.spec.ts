import { expect, test, type Page } from "@playwright/test";

async function expectFittedFormula(page: Page) {
  const frame = page.locator(".math-fit");
  await expect(frame).toHaveCount(1);
  await expect.poll(async () => frame.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const content = element.querySelector<HTMLElement>(".math-fit-content")!.getBoundingClientRect();
    const tag = element.querySelector<HTMLElement>(".katex-html > .tag")!.getBoundingClientRect();
    return box.height > 0 && content.width <= box.width + 1
      && Math.abs(content.height - box.height) <= 1
      && Math.abs((content.left + content.right) - (box.left + box.right)) <= 2
      && tag.left >= box.left - 1 && tag.right <= box.right + 1;
  })).toBe(true);
}

for (const width of [1280, 390]) {
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    test(`fits tagged streaming math at ${width}px with motion ${reducedMotion}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setViewportSize({ width, height: 844 });
      await page.emulateMedia({ reducedMotion });
      await page.goto("/browser/fixture.html?case=display-math");
      await page.evaluate(() => document.fonts.ready);
      await expectFittedFormula(page);
      await page.getByRole("button", { name: "Advance stream" }).click();
      await expectFittedFormula(page);
      await expect.poll(() => page.locator(".math-fit").getAttribute("data-math-scale").then(Number)).toBeLessThan(1);
      await page.getByRole("button", { name: "Advance stream" }).click();
      await expect(page.locator(".katex-html > .tag")).toHaveText("(1000000)");
      await expectFittedFormula(page);
      await page.getByRole("button", { name: "Complete", exact: true }).click();
      await expectFittedFormula(page);
      await page.setViewportSize({ width: width === 390 ? 1280 : 390, height: 844 });
      await expectFittedFormula(page);
      await page.locator(".math-fit-content").evaluate((element) => { element.style.fontSize = "24px"; });
      await expectFittedFormula(page);
      expect(errors).toEqual([]);
    });
  }
}
