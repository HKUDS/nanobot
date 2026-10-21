import { expect, test, type Page } from "@playwright/test";

async function samplePhases(page: Page) {
  return page.getByRole("img", { name: "Agent running", exact: true }).evaluateAll((nodes) => nodes.map((node) => {
    const animation = node.getAnimations({ subtree: true })[0];
    const duration = animation.effect!.getTiming().duration as number;
    return (Number(animation.currentTime) % duration) / duration;
  }));
}

test("sidebar activity stays in phase across staggered starts, selection and remounts", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=sidebar-activity");
  await expect(page.getByRole("img", { name: "Agent running", exact: true })).toHaveCount(1);
  for (let count = 2; count <= 4; count++) {
    // Stagger arrivals on the actual animation clock, rather than mounting every row together.
    const previous = (await samplePhases(page))[0];
    await expect.poll(async () => Math.abs((await samplePhases(page))[0] - previous)).toBeGreaterThan(0.15);
    await page.getByRole("button", { name: "Start next conversation" }).click();
    await expect(page.getByRole("img", { name: "Agent running", exact: true })).toHaveCount(count);
  }
  const samples = await page.evaluate(() => new Promise<number[][]>((resolve) => {
    const result: number[][] = [];
    const start = performance.now();
    const sample = () => {
      result.push(Array.from(document.querySelectorAll('[role="img"][aria-label="Agent running"]')).map((node) => {
        const animation = node.getAnimations({ subtree: true })[0];
        return (Number(animation.currentTime) % Number(animation.effect!.getTiming().duration)) / Number(animation.effect!.getTiming().duration);
      }));
      if (performance.now() - start < 1500) requestAnimationFrame(sample);
      else resolve(result);
    };
    requestAnimationFrame(sample);
  }));
  expect(samples.length).toBeGreaterThan(10);
  expect(new Set(samples.map((sample) => sample[0].toFixed(2))).size).toBeGreaterThan(10);
  for (const phases of samples) expect(Math.max(...phases) - Math.min(...phases)).toBeLessThan(0.001);

  await page.getByRole("button", { name: "@jaru Locate messages", exact: true }).click();
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await expect(page.getByRole("img", { name: "Agent running", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await expect(page.getByRole("img", { name: "Agent running", exact: true })).toHaveCount(4);
  const phases = await samplePhases(page);
  expect(Math.max(...phases) - Math.min(...phases)).toBeLessThan(0.001);
});

for (const width of [1280, 390]) {
  test(`sidebar Ring follows the neutral theme at ${width}px and respects live motion preferences`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/browser/fixture.html?case=sidebar-activity&all");
    const indicators = page.getByRole("img", { name: "Agent running", exact: true });
    await expect(indicators).toHaveCount(4);
    const colors: string[] = [];
    for (const dark of [false, true]) {
      await page.evaluate((enabled) => document.documentElement.classList.toggle("dark", enabled), dark);
      const actual = await indicators.evaluateAll((nodes) => nodes.map((node) => {
        const svg = node.querySelector("svg")!;
        const reference = document.createElement("span");
        reference.style.color = "hsl(var(--sidebar-muted-foreground))";
        node.append(reference);
        const expectedColor = getComputedStyle(reference).color;
        reference.remove();
        const rect = svg.getBoundingClientRect();
        return { color: getComputedStyle(svg).color, expectedColor, size: [rect.width, rect.height] };
      }));
      for (const item of actual) {
        expect(item.color).toBe(item.expectedColor);
        expect(item.size).toEqual([12, 12]);
      }
      colors.push(actual[0].color);
      await page.getByRole("button", { name: "@jaru Locate messages", exact: true }).hover();
      await page.getByRole("button", { name: "@goyo Refine message bubbles", exact: true }).click();
      expect(await indicators.evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node.querySelector("svg")!).color)))
        .toEqual(Array(4).fill(actual[0].color));
    }
    expect(colors[0]).not.toBe(colors[1]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    for (const reducedMotion of ["reduce", "no-preference"] as const) {
      await page.emulateMedia({ reducedMotion });
      await expect.poll(() => indicators.evaluateAll((nodes) => nodes.map((node) => node.getAnimations({ subtree: true }).length)))
        .toEqual(Array(4).fill(reducedMotion === "reduce" ? 0 : 1));
      if (reducedMotion === "no-preference") {
        const phases = await samplePhases(page);
        expect(Math.max(...phases) - Math.min(...phases)).toBeLessThan(0.001);
      }
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.getByRole("button", { name: "Reset conversations" }).click();
    await page.getByRole("button", { name: "Start next conversation" }).click();
    await expect(indicators).toHaveCount(2);
    expect(await indicators.evaluateAll((nodes) => nodes.map((node) => node.getAnimations({ subtree: true }).length))).toEqual([0, 0]);
  });
}
