import { expect, test, type Locator } from "@playwright/test";

async function readingPosition(body: Locator) {
  return body.evaluate((node) => {
    const bounds = node.getBoundingClientRect();
    const units = Array.from(node.querySelectorAll<HTMLElement>("[data-thread-display-unit]"));
    const unit = units.find((element) => element.getBoundingClientRect().bottom > bounds.top)!;
    return {
      sources: unit.dataset.threadScrollSources!,
      offset: unit.getBoundingClientRect().top - bounds.top,
      count: units.length,
      top: node.scrollTop,
    };
  });
}

async function browseExpandedHistory(body: Locator) {
  await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(1);
  await body.hover();
  await body.page().mouse.wheel(0, -100);
  await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(50);
  await body.evaluate((node) => { node.scrollTop = 0; });
  await expect(body.locator("[data-thread-display-unit]")).toHaveCount(240);
  await body.evaluate((node) => { node.scrollTop = (node.scrollHeight - node.clientHeight) / 2 + 17; });
  await expect(body.page().getByRole("button", { name: "Scroll to bottom", exact: true })).toBeVisible();
  // Let the real display units settle after offscreen rows materialize.
  await expect.poll(async () => (await readingPosition(body)).top).toBeGreaterThan(500);
  return readingPosition(body);
}

for (const external of [false, true]) {
  test(`restores A-B-A reading position and the expanded visible window (${external ? "external" : "viewport"} store)`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto(`/browser/thread-reading-state.html${external ? "?external" : ""}`);
    const body = page.getByTestId("thread-message-region");
    const before = await browseExpandedHistory(body);
    await page.getByRole("button", { name: "Select B", exact: true }).click();
    await expect(body.locator("[data-thread-display-unit]")).toHaveCount(14);
    await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(1);
    if (external) {
      await page.getByRole("button", { name: "Detach viewport" }).click();
      await expect(body).toHaveCount(0);
      await page.getByRole("button", { name: "Mount viewport" }).click();
    }
    await page.getByRole("button", { name: "Select A pending" }).click();
    await expect(body.locator("[data-thread-display-unit]")).toHaveCount(14);
    await page.getByRole("button", { name: "Hydrate A" }).click();
    await expect(body.locator("[data-thread-display-unit]")).toHaveCount(before.count);
    await expect.poll(async () => (await readingPosition(body)).sources).toBe(before.sources);
    await expect.poll(async () => Math.abs((await readingPosition(body)).offset - before.offset)).toBeLessThan(1);
    await expect.poll(async () => Math.abs((await readingPosition(body)).top - before.top)).toBeLessThan(1);
    await page.setViewportSize({ width: 1200, height: 760 });
    await expect.poll(async () => Math.abs((await readingPosition(body)).offset - before.offset)).toBeLessThan(1);
    await page.getByRole("button", { name: "Force bottom" }).click();
    await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(1);
    await page.getByRole("button", { name: "Select B", exact: true }).click();
    await page.getByRole("button", { name: "Select A", exact: true }).click();
    await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(1);
  });
}

test("restores the source-aware anchor after replay replaces message IDs", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/thread-reading-state.html");
  const body = page.getByTestId("thread-message-region");
  const before = await browseExpandedHistory(body);
  const sequence = (JSON.parse(before.sources) as string[]).find((source) => (JSON.parse(source) as string[])[1] === "sequence")!;
  await page.getByRole("button", { name: "Select B", exact: true }).click();
  await page.getByRole("button", { name: "Replay IDs" }).click();
  await page.getByRole("button", { name: "Select A", exact: true }).click();
  await expect(body.locator("[data-thread-display-unit]")).toHaveCount(before.count);
  await expect.poll(async () => (JSON.parse((await readingPosition(body)).sources) as string[]).includes(sequence)).toBe(true);
  await expect.poll(async () => Math.abs((await readingPosition(body)).offset - before.offset)).toBeLessThan(1);
});

test("cold HTTP 503 shows the error retry control, not welcome, and retry recovers", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  let requests = 0;
  await page.route("**/reading-fixture-history", (route) => route.fulfill({ status: ++requests === 1 ? 503 : 200, body: "{}" }));
  await page.goto("/browser/thread-reading-state.html?cold-error");
  await expect(page.getByText("Welcome fixture")).toHaveCount(0);
  await expect(page.getByTestId("thread-welcome-layout")).toHaveCount(0);
  const retry = page.getByRole("button", { name: "Loading failed. Retry" });
  await expect(retry).toBeVisible();
  await retry.hover();
  await expect(page.getByRole("tooltip", { name: "HTTP 503: unavailable" })).toBeVisible();
  await retry.click();
  await expect(page.getByText("A message 0", { exact: true })).toBeVisible();
  await expect(retry).toHaveCount(0);
  expect(requests).toBe(2);
});

test("cached HTTP 503 stays visible at the tail and retry preserves the reading camera", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  let requests = 0;
  await page.route("**/reading-fixture-history", (route) => route.fulfill({ status: ++requests === 1 ? 503 : 200, body: "{}" }));
  await page.goto("/browser/thread-reading-state.html?cached-error");
  const body = page.getByTestId("thread-message-region");
  const retry = page.getByRole("button", { name: "Loading failed. Retry" });
  await expect(retry).toBeVisible();
  await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThan(1);
  await retry.hover();
  await expect(page.getByRole("tooltip", { name: "HTTP 503: unavailable" })).toBeVisible();
  await body.hover();
  await page.mouse.wheel(0, -200);
  await expect.poll(() => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(100);
  const before = await readingPosition(body);
  await retry.click();
  await expect(retry).toHaveCount(0);
  await expect.poll(async () => Math.abs((await readingPosition(body)).top - before.top)).toBeLessThan(1);
  await expect(body.locator("[data-thread-display-unit]")).toHaveCount(120);
  expect(requests).toBe(2);
});
