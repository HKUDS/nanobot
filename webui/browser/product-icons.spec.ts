import { expect, test } from "@playwright/test";

test("settings gear outline is symmetric about its circular hub", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=settings-icon");
  const icon = page.getByRole("button", { name: "Settings", exact: true }).locator("svg");
  const error = await icon.evaluate((element) => {
    const outline = element.querySelector("path")!;
    const hub = element.querySelector("circle")!;
    const length = outline.getTotalLength();
    let maximum = 0;
    for (let index = 0; index < 64; index++) {
      const distance = length * index / 128;
      const point = outline.getPointAtLength(distance);
      const opposite = outline.getPointAtLength(distance + length / 2);
      maximum = Math.max(maximum, Math.hypot(
        point.x + opposite.x - 2 * hub.cx.baseVal.value,
        point.y + opposite.y - 2 * hub.cy.baseVal.value,
      ));
    }
    return maximum;
  });
  expect(error).toBeLessThan(0.001);
});
