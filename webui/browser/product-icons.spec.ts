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

test("settings hover rotates the outline without transforming the hub", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/browser/fixture.html?case=settings-icon");
  const button = page.getByRole("button", { name: "Settings", exact: true });
  const icon = button.locator("svg");
  for (const hovered of [true, false]) {
    const sample = icon.evaluate((element) => new Promise<{ hubChange: number; rotatingFrames: number }>((resolve) => {
      const hub = element.querySelector("circle")!;
      const outline = element.querySelector("path")!;
      const initial = hub.getScreenCTM()!;
      const started = performance.now();
      let hubChange = 0;
      let rotatingFrames = 0;
      function read() {
        const matrix = hub.getScreenCTM()!;
        for (const key of ["a", "b", "c", "d", "e", "f"] as const) {
          hubChange = Math.max(hubChange, Math.abs(matrix[key] - initial[key]));
        }
        const rotation = outline.getScreenCTM()!;
        if (rotation.a > 0.01 && rotation.b > 0.01) rotatingFrames++;
        if (performance.now() - started < 450) requestAnimationFrame(read);
        else resolve({ hubChange, rotatingFrames });
      }
      read();
    }));
    if (hovered) await button.hover();
    else await page.mouse.move(0, 0);
    const result = await sample;
    expect(result.rotatingFrames).toBeGreaterThan(0);
    expect(result.hubChange).toBeLessThan(0.0001);
  }
});
