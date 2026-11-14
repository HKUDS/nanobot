import { expect, test } from "@playwright/test";

const path = "/browser/fixture.html?case=activity-wheel";

test.beforeEach(async ({ page }) => {
  // Keep network timing out of this test; the real favicon component loads the image.
  await page.route(/https:\/\/favicon\.im\//, (route) => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" rx="3" fill="#17624c"/></svg>',
  }));
  await page.goto(path);
});

test("the collapsed row rolls with its icon and a burst lands on the latest activity", async ({ page }) => {
  const toggle = page.getByRole("button", { name: /处理中/ });
  const wheel = page.getByTestId("latest-activity-wheel");
  const next = page.getByRole("button", { name: "下一条" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("agent-activity-content")).toHaveCount(0);
  await expect(wheel).toContainText("brief.md");
  const headerBox = (await toggle.boundingBox())!;
  const wheelBox = (await wheel.boundingBox())!;
  expect(wheelBox.x).toBeGreaterThan(headerBox.x + headerBox.width);
  expect(wheelBox.y + wheelBox.height / 2).toBeCloseTo(headerBox.y + headerBox.height / 2, 0);
  const iconOffset = await wheel.evaluate((element) => {
    const icon = element.querySelector("[data-activity-marker] svg")!.getBoundingClientRect();
    const label = element.previousElementSibling!.querySelector("span")!.getBoundingClientRect();
    return icon.top + icon.height / 2 - (label.top + label.height / 2);
  });
  expect(Math.abs(iconOffset)).toBeLessThan(0.2);
  const height = (await toggle.boundingBox())!.height;

  // This is a status update on the same tool, not a new row.
  await next.click();
  await expect(wheel).toContainText("读取文件");
  await expect(wheel.getByTestId("activity-step")).toHaveCount(1);

  // Observe the two real row boxes during the animation, including the incoming logo.
  await next.click();
  await expect(wheel).toContainText("夜间列车旅行指南");
  const motion = await wheel.evaluate(async (element) => {
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent === "下一条")!;
    button.click();
    const end = performance.now() + 600;
    do {
      await new Promise(requestAnimationFrame);
      const rows = element.querySelectorAll<HTMLElement>('[data-testid="activity-step"]');
      const incoming = rows[1];
      if (!incoming?.querySelector("img")) continue;
      const top = incoming.parentElement!.getBoundingClientRect().top - element.getBoundingClientRect().top;
      if (top > 1 && top < element.clientHeight) {
        return {
          gap: top + element.getBoundingClientRect().top - rows[0].parentElement!.getBoundingClientRect().top,
          height: element.clientHeight,
        };
      }
    } while (performance.now() < end);
    return null;
  });
  expect(motion).not.toBeNull();
  expect(motion!.gap).toBeCloseTo(motion!.height, 0);
  await expect(wheel.getByTestId("activity-step")).toHaveCount(1);
  await expect(wheel).toContainText("Planning an overnight rail trip");
  await expect(wheel.locator("img")).toHaveJSProperty("complete", true);
  expect((await toggle.boundingBox())!.height).toBe(height);

  await page.getByRole("button", { name: "快速播放" }).click();
  await expect(wheel).toContainText("A better way to travel overnight", { timeout: 2200 });
  await expect(wheel.getByTestId("activity-step")).toHaveCount(1, { timeout: 500 });
  await toggle.focus();
  await toggle.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(wheel).toHaveCount(0);
  await expect(toggle).toBeFocused();
  await expect(page.getByRole("link", { name: /Night train routes across Europe/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /A better way to travel overnight/ })).toBeVisible();
  await toggle.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(wheel).toContainText("A better way to travel overnight");
});

test("narrow reduced-motion preview replaces the row without scrolling the page", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  const wheel = page.getByTestId("latest-activity-wheel");
  await expect(wheel).toContainText("brief.md");
  // Change the system preference while the wheel is already mounted.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "切换主题" }).click();
  const toggle = page.getByRole("button", { name: /处理中/ });
  const next = page.getByRole("button", { name: "下一条" });
  await next.click({ clickCount: 2 });
  await expect(wheel).toContainText("夜间列车旅行指南");
  const maxTravel = await next.evaluate(async (button) => {
    (button as HTMLButtonElement).click();
    let travel = 0;
    for (let frame = 0; frame < 6; frame += 1) {
      await new Promise(requestAnimationFrame);
      const strip = document.querySelector('[data-testid="latest-activity-wheel"]')!;
      const rows = strip.querySelectorAll('[data-testid="activity-step"]');
      const row = rows[rows.length - 1]?.parentElement;
      if (row) travel = Math.max(travel, Math.abs(row.getBoundingClientRect().top - strip.getBoundingClientRect().top));
    }
    return travel;
  });
  expect(maxTravel).toBeLessThan(1);
  await expect(wheel).toContainText("Planning an overnight rail trip");
  await expect(wheel.getByTestId("activity-step")).toHaveCount(1);
  expect(await wheel.evaluate((element) => {
    const row = element.firstElementChild!;
    return Math.abs(row.getBoundingClientRect().top - element.getBoundingClientRect().top);
  })).toBeLessThan(1);
  const header = (await toggle.boundingBox())!;
  const row = (await wheel.boundingBox())!;
  expect(row.y).toBeGreaterThanOrEqual(header.y + header.height - 0.2);
  expect(row.width).toBeGreaterThan(header.width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(360);
});

test("the elapsed label keeps a compact gap before the collapsed activity", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 740 });
  const start = new Date("2026-01-01T00:00:00Z");
  await page.clock.install({ time: start });
  await page.clock.pauseAt(new Date(start.getTime() + 60_000));
  await page.reload();
  const toggle = page.getByRole("button", { name: /处理中/ });
  const wheel = page.getByTestId("latest-activity-wheel");
  await expect(wheel).toBeVisible();

  let initialGap: number | undefined;
  let elapsed = 0;
  for (const [seconds, label] of [[1, "1s"], [9, "9s"], [10, "10s"], [20, "20s"], [59, "59s"], [60, "1m"], [61, "1m 1s"]] as const) {
    await page.clock.fastForward((seconds - elapsed) * 1000);
    elapsed = seconds;
    await expect(toggle).toHaveAccessibleName(`处理中 ${label}`);
    const wheelBox = (await wheel.boundingBox())!;
    const headerBox = (await toggle.boundingBox())!;
    const gap = wheelBox.x - (headerBox.x + headerBox.width);
    initialGap ??= gap;
    expect(Math.abs(gap - initialGap), `activity gap at ${label}`).toBeLessThan(0.2);
    expect(gap).toBeLessThanOrEqual(8);
  }
});

test("the working label stays in place when activity is expanded and collapsed", async ({ page }) => {
  for (const width of [960, 360]) {
    await page.setViewportSize({ width, height: 740 });
    const toggle = page.getByRole("button", { name: /处理中/ });
    const labelPosition = () => toggle.evaluate((button) => {
      const label = button.querySelector("[data-sheen-text]")!;
      const range = document.createRange();
      range.selectNodeContents(label);
      const { x, y } = range.getBoundingClientRect();
      return { x, y, width: button.getBoundingClientRect().width };
    });
    const collapsed = await labelPosition();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const expanded = await labelPosition();
    expect(Math.abs(expanded.x - collapsed.x)).toBeLessThan(0.2);
    expect(Math.abs(expanded.y - collapsed.y)).toBeLessThan(0.2);
    expect(Math.abs(expanded.width - collapsed.width)).toBeLessThan(0.2);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    const collapsedAgain = await labelPosition();
    expect(Math.abs(collapsedAgain.x - collapsed.x)).toBeLessThan(0.2);
    expect(Math.abs(collapsedAgain.y - collapsed.y)).toBeLessThan(0.2);
  }
});
