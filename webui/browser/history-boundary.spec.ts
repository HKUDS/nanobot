import { expect, test, type Locator, type Page } from "@playwright/test";

function historyPage(start: number, count = 12, more = start > 0) {
  return { schemaVersion: 3, projection: "events", events: Array.from({ length: Math.min(count, 52 - start) }, (_, offset) => [
    { event: "user_message", chat_id: "boundary-a", projection_id: `u${start + offset}`, text: `Question ${start + offset}`, starts_turn: true },
    { event: "message", chat_id: "boundary-a", projection_id: `a${start + offset}`, text: "Historical answer.\n\n".repeat(8) },
  ]).flat(), page: { before_cursor: String(start), after_cursor: String(start + count), user_message_offset: start,
    has_more_before: more, has_more_after: start + count < 52 } };
}

async function installHistory(page: Page) {
  const reads: string[] = [];
  const pending: Array<(value: "success" | "error") => void> = [];
  await page.route("**/api/sessions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/prompts")) return route.fulfill({ json: {
      prompts: Array.from({ length: 52 }, (_, i) => ({ id: `u${i}`, preview: `Question ${i}`, answerPreview: "Historical answer", turnId: `turn${i}`, cursor: String(i), createdAt: i + 1 })),
    } });
    if (!url.pathname.endsWith("/webui-thread")) return route.fulfill({ json: {} });
    if (url.pathname.includes("boundary-b")) return route.fulfill({ json: historyPage(0, 2, false) });
    const cursor = url.searchParams.get("before") ?? url.searchParams.get("after");
    if (cursor === null) return route.fulfill({ json: historyPage(40) });
    reads.push(url.search);
    const outcome = await new Promise<"success" | "error">((resolve) => pending.push(resolve));
    if (outcome === "error") return route.fulfill({ status: 503, body: "History unavailable" });
    const start = url.searchParams.has("after") ? Number(cursor) : Math.max(0, Number(cursor) - 12);
    const count = url.searchParams.has("after") ? 12 : Number(cursor) - start;
    await route.fulfill({ json: historyPage(start, count, start > 0) });
  });
  return { reads, complete: (outcome: "success" | "error" = "success") => pending.shift()?.(outcome) };
}

// Positioning is synthetic; gesture assertions below use browser wheel / CDP touch input.
async function positionAtTop(body: Locator) {
  return body.evaluate((node) => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
    node.scrollTop = 0;
    node.dispatchEvent(new TouchEvent("touchstart", { bubbles: true, touches: [new Touch({ identifier: 1, target: node, clientX: 180, clientY: 200 })] }));
    node.dispatchEvent(new TouchEvent("touchend", { bubbles: true }));
    const first = node.querySelector("[data-thread-display-unit]")!;
    return first.getBoundingClientRect().top - node.getBoundingClientRect().top;
  });
}

async function displacement(body: Locator) {
  return body.evaluate((node) => new DOMMatrix(getComputedStyle(node).transform).m42);
}

async function stableLayout(body: Locator) {
  await body.evaluate(async (node) => {
    let previous = -1;
    let stable = 0;
    for (let i = 0; i < 120 && stable < 8; i++) {
      await new Promise(requestAnimationFrame);
      const value = node.scrollHeight + node.scrollTop;
      stable = value === previous ? stable + 1 : 0;
      previous = value;
    }
  });
}

async function anchorOffset(body: Locator, text: string) {
  return body.getByText(text, { exact: true }).evaluate((node) => {
    const unit = node.closest("[data-thread-display-unit]")!;
    const scroller = node.closest(".thread-message-viewport")!;
    return unit.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  });
}

test("continuous wheel input holds real loading visible and preserves the reading anchor through prepend and delayed layout", async ({ page }) => {
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  await expect(body).toBeVisible();
  await stableLayout(body);
  const nativeTop = await body.evaluate((node) => node.scrollTop);
  await body.hover();
  await page.mouse.wheel(0, -100);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeLessThan(nativeTop);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(0);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(80, 0);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(0);
  await body.hover();
  for (const delta of [-100, -70, -45, -28, -16, -8, -3]) await page.mouse.wheel(0, delta);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  await expect(page.locator(".thread-history-blocks")).toHaveCSS("color", "rgb(211, 94, 20)");
  expect(history.reads).toHaveLength(1);
  await expect.poll(() => displacement(body)).toBeCloseTo(20, 1);
  const still = await displacement(body);
  await page.waitForTimeout(150);
  expect(Math.abs(await displacement(body) - still)).toBeLessThan(0.1);
  await page.screenshot({ path: "test-results/history-boundary-loading.png" });

  await body.evaluate((node) => { node.scrollTop = 500; });
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  await expect.poll(() => displacement(body)).toBe(0);
  const reading = await anchorOffset(body, "Question 40");
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  expect(Math.abs(await anchorOffset(body, "Question 40") - reading)).toBeLessThan(1);
  expect(history.reads).toHaveLength(1);

  await body.getByText("Question 28", { exact: true }).evaluate((node) => {
    const delayed = document.createElement("div");
    delayed.style.height = "160px";
    node.closest("[data-thread-display-unit]")!.prepend(delayed);
  });
  await page.waitForTimeout(100);
  expect(Math.abs(await anchorOffset(body, "Question 40") - reading)).toBeLessThan(1);
});

test("touch short-pull cancellation, armed release, loading takeover, and conversation changes converge", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
  const page = await context.newPage();
  const history = await installHistory(page);
  try {
    await page.goto("/browser/fixture.html?case=history-boundary");
    const body = page.getByTestId("thread-message-region");
    await expect(body).toBeVisible();
    await stableLayout(body);
    await positionAtTop(body);
    const cdp = await context.newCDPSession(page);
    const touch = async (type: "touchStart" | "touchMove" | "touchEnd", y = 200, x = 180) => cdp.send("Input.dispatchTouchEvent", {
      type, touchPoints: type === "touchEnd" ? [] : [{ x, y, id: 1 }],
    });
    await touch("touchStart");
    await touch("touchMove", 210, 300);
    await touch("touchEnd");
    expect(await displacement(body)).toBe(0);
    expect(history.reads).toHaveLength(0);
    await touch("touchStart");
    await touch("touchMove", 240);
    const pulled = await displacement(body);
    expect(pulled).toBeGreaterThan(0);
    await touch("touchEnd");
    expect(await displacement(body)).toBeGreaterThan(0);
    await expect.poll(() => displacement(body)).toBe(0);
    expect(history.reads).toHaveLength(0);

    await touch("touchStart");
    await touch("touchMove", 330);
    await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeVisible();
    expect(await displacement(body)).toBeGreaterThanOrEqual(42);
    expect(history.reads).toHaveLength(0);
    await touch("touchEnd");
    await expect.poll(() => history.reads.length).toBe(1);
    await expect.poll(() => displacement(body)).toBeCloseTo(20, 1);
    await touch("touchStart");
    await touch("touchMove", 240);
    expect(await displacement(body)).toBeGreaterThan(20);
    await touch("touchEnd");
    await expect.poll(() => displacement(body)).toBeCloseTo(20, 1);
    expect(history.reads).toHaveLength(1);
    await page.getByRole("button", { name: "Switch conversation" }).click();
    await expect(body.getByText("Question 1", { exact: true })).toBeVisible();
    expect(await displacement(body)).toBe(0);
    history.complete();
    await page.waitForTimeout(100);
    await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  } finally { await context.close(); }
});

test("failure stays actionable away from the top; retry, fast completion and exhausted reduced-motion state remain truthful", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary");
  await page.locator("html").evaluate((node) => node.classList.add("dark"));
  await expect(page.locator("main")).toHaveCSS("background-color", "rgb(48, 48, 48)");
  const body = page.getByTestId("thread-message-region");
  await expect(body).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await page.getByRole("button", { name: "Load earlier messages", exact: true }).click();
  await expect.poll(() => history.reads.length).toBe(1);
  expect(await displacement(body)).toBe(0);
  const block = page.locator(".thread-history-blocks > span").first();
  await expect(block).toHaveCSS("background-color", "rgb(211, 94, 20)");
  expect(await block.evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
  await body.evaluate((node) => { node.scrollTop = 600; });
  history.complete("error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  await expect(retry).toBeInViewport();
  const failedBlocks = retry.locator(".thread-history-blocks");
  await expect(failedBlocks).toHaveCSS("width", "24px");
  await expect(failedBlocks).toHaveCSS("height", "24px");
  await expect(failedBlocks).toHaveCSS("color", "rgb(252, 165, 165)");
  await expect(failedBlocks.locator("span").first()).toHaveCSS("animation-name", "none");
  await expect(failedBlocks.locator("span").first()).toHaveCSS("transform", "none");
  await retry.focus();
  await expect(page.getByRole("tooltip")).toHaveText("HTTP 503");
  await retry.click();
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(page.locator(".thread-history-blocks")).toHaveCSS("width", "20px");
  await expect(page.locator(".thread-history-blocks")).toHaveCSS("color", "rgb(211, 94, 20)");
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(page.locator('.thread-history-status[data-state="exhausted"]')).toHaveCount(0);
  for (const start of [16, 4, 0]) {
    await positionAtTop(body);
    await page.getByRole("button", { name: "Load earlier messages", exact: true }).click();
    await expect.poll(() => history.reads.length).toBe(start === 16 ? 3 : start === 4 ? 4 : 5);
    history.complete();
    await expect(body.getByText(`Question ${start}`, { exact: true })).toBeAttached();
  }
  await positionAtTop(body);
  await expect(page.locator('.thread-history-status[data-state="exhausted"]')).toBeInViewport();
  await body.hover();
  await page.mouse.wheel(0, -120);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(5);
  await page.screenshot({ path: "test-results/history-boundary-exhausted-dark.png" });
});

test("local cached windows expand without network loading and only the complete beginning is exhausted", async ({ page }) => {
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary&local=1");
  const body = page.getByTestId("thread-message-region");
  await expect(body.getByText("Cached message 160", { exact: true })).toBeAttached();
  await stableLayout(body);
  const localAnchor = await positionAtTop(body);
  await expect(body.getByText("Cached message 40", { exact: true })).toBeAttached();
  await stableLayout(body);
  await test.info().attach("local-window-anchor", { body: JSON.stringify({
    before: localAnchor, after: await anchorOffset(body, "Cached message 160"),
  }), contentType: "application/json" });
  await expect(page.locator('.thread-history-status[data-state="exhausted"]')).toHaveCount(0);
  await positionAtTop(body);
  await expect(body.getByText("Cached message 0", { exact: true })).toBeAttached();
  await positionAtTop(body);
  await expect(page.locator('.thread-history-status[data-state="exhausted"]')).toBeInViewport();
  expect(history.reads).toHaveLength(0);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
});

test("navigation-window loading and errors remain visible and retry uses the navigation request owner", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser/fixture.html?case=history-boundary&navigate=1");
  const body = page.getByTestId("thread-message-region");
  await expect(body).toBeVisible();
  const rail = page.getByTestId("prompt-rail-scroll");
  await rail.getByRole("button").first().focus();
  await page.keyboard.press("Home");
  await page.getByRole("button", { name: "Jump to message: Question 38", exact: true }).click();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  history.complete();
  await expect(body.getByText("Question 38", { exact: true })).toBeInViewport();
  await stableLayout(body);
  await body.hover();
  await page.mouse.wheel(0, 10000);
  await expect.poll(() => history.reads.length).toBe(2);
  history.complete();
  await expect(body.getByText("Question 51", { exact: true })).toBeAttached();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  history.complete("error");
  await page.getByRole("button", { name: "Loading failed. Retry", exact: true }).click();
  await expect.poll(() => history.reads.length).toBe(4);
  history.complete();
  await expect(body.getByText("Question 26", { exact: true })).toBeAttached();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await positionAtTop(body);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&after=50", "?limit=24&before=38", "?limit=24&before=38"]);
});
