import { expect, test, type Locator, type Page } from "@playwright/test";

function historyPage(start: number, count = 12, more = start > 0) {
  return { schemaVersion: 3, projection: "events", events: Array.from({ length: Math.min(count, 52 - start) }, (_, offset) => [
    { event: "user_message", chat_id: "boundary-a", projection_id: `u${start + offset}`, text: `Question ${start + offset}`, starts_turn: true },
    { event: "message", chat_id: "boundary-a", projection_id: `a${start + offset}`, text: "Historical answer.\n\n".repeat(8) },
  ]).flat(), page: { before_cursor: String(start), after_cursor: String(start + count), user_message_offset: start,
    has_more_before: more, has_more_after: start + count < 52 } };
}

async function installHistory(page: Page, initialStart = 40, initialCount = 12) {
  const reads: string[] = [];
  const pending: Array<(value: "success" | "error") => void> = [];
  let immediate = false;
  await page.route("**/api/sessions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/prompts")) return route.fulfill({ json: {
      prompts: Array.from({ length: 52 }, (_, i) => ({ id: `u${i}`, preview: `Question ${i}`, answerPreview: "Historical answer", turnId: `turn${i}`, cursor: String(i), createdAt: i + 1 })),
    } });
    if (!url.pathname.endsWith("/webui-thread")) return route.fulfill({ json: {} });
    if (url.pathname.includes("boundary-b")) return route.fulfill({ json: historyPage(0, 2, false) });
    const cursor = url.searchParams.get("before") ?? url.searchParams.get("after");
    if (cursor === null) return route.fulfill({ json: historyPage(initialStart, initialCount) });
    reads.push(url.search);
    const outcome = immediate ? "success" : await new Promise<"success" | "error">((resolve) => pending.push(resolve));
    if (outcome === "error") return route.fulfill({ status: 503, body: "History unavailable" });
    const start = url.searchParams.has("after") ? Number(cursor) : Math.max(0, Number(cursor) - 12);
    const count = url.searchParams.has("after") ? 12 : Number(cursor) - start;
    await route.fulfill({ json: historyPage(start, count, start > 0) });
  });
  return {
    reads,
    respondImmediately: (value: boolean) => { immediate = value; },
    complete: (outcome: "success" | "error" = "success") => pending.shift()?.(outcome),
  };
}

async function installShortHistory(page: Page) {
  let reads = 0;
  await page.route("**/api/sessions/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/prompts")) return route.fulfill({ json: { prompts: [] } });
    if (!pathname.endsWith("/webui-thread")) return route.fulfill({ json: {} });
    reads++;
    const history = historyPage(0, 1, false);
    return route.fulfill({ json: { ...history, events: history.events.map((event) => ({
      ...event, text: event.event === "message" ? "Short answer." : event.text,
    })) } });
  });
  return () => reads;
}

// Positioning is synthetic; gesture assertions below use browser wheel / CDP touch input.
async function positionAtTop(body: Locator) {
  return body.evaluate((node) => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
    node.scrollTop = 0;
    node.dispatchEvent(new TouchEvent("touchstart", { bubbles: true, touches: [new Touch({ identifier: 1, target: node, clientX: 180, clientY: 200 })] }));
    node.dispatchEvent(new TouchEvent("touchend", { bubbles: true }));
    const first = node.querySelector("[data-thread-display-unit]")!;
    return first.getBoundingClientRect().top;
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

async function anchorTop(body: Locator, text: string) {
  return body.getByText(text, { exact: true }).evaluate((node) =>
    node.closest("[data-thread-display-unit]")!.getBoundingClientRect().top);
}

// Use the fixed viewport, never the transformed scroller, as the coordinate frame.
async function historyGeometry(body: Locator, text: string) {
  return body.getByText(text, { exact: true }).evaluate((node) => {
    const unit = node.closest("[data-thread-display-unit]")!.getBoundingClientRect();
    const frame = node.closest(".thread-viewport-frame")!.getBoundingClientRect();
    const scroller = node.closest<HTMLElement>(".thread-message-viewport")!;
    const header = node.closest(".thread-viewport")!.querySelector(".thread-history-status")!.getBoundingClientRect();
    const slot = scroller.querySelector(".thread-history-slot");
    return {
      headerTop: header.top, headerBottom: header.bottom, headerHeight: header.height,
      visibleHeight: Math.max(0, Math.min(header.bottom, frame.bottom) - Math.max(header.top, frame.top)),
      anchorTop: unit.top, frameTop: frame.top, scrollTop: scroller.scrollTop,
      transformY: new DOMMatrix(getComputedStyle(scroller).transform).m42,
      slotHeight: slot?.getBoundingClientRect().height ?? 0,
      slotBeforeKey: slot?.parentElement?.nextElementSibling?.getAttribute("data-thread-display-unit") ?? null,
      firstKey: scroller.querySelector("[data-thread-display-unit]")?.getAttribute("data-thread-display-unit"),
    };
  });
}

type HistoryGeometry = Awaited<ReturnType<typeof historyGeometry>>;

async function expectCoordinates(body: Locator, text: string, reference: HistoryGeometry) {
  let latest = reference;
  try {
    await expect.poll(async () => {
      latest = await historyGeometry(body, text);
      return Math.max(...(["headerTop", "headerBottom", "anchorTop", "frameTop"] as const)
        .map((key) => Math.abs(latest[key] - reference[key])));
    }, { message: `${text}: header and reading unit must keep their fixed viewport coordinates` }).toBeLessThan(1);
  } catch (error) {
    const diagnostic = JSON.stringify({ text, before: reference, after: latest });
    console.log("history-coordinate-failure", diagnostic);
    await test.info().attach("history-coordinate-failure", { body: diagnostic, contentType: "application/json" });
    throw error;
  }
}

async function expectHeld(body: Locator, text: string) {
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  await expect.poll(() => displacement(body)).toBe(0);
  await expect.poll(async () => (await historyGeometry(body, text)).visibleHeight).toBeCloseTo(48, 0);
  return historyGeometry(body, text);
}

function expectSameScroll(before: HistoryGeometry, after: HistoryGeometry, delta: number) {
  expect(delta).toBeGreaterThan(0);
  expect(Math.abs(after.headerTop - before.headerTop + delta)).toBeLessThan(1);
  expect(Math.abs(after.anchorTop - before.anchorTop + delta)).toBeLessThan(1);
}

async function expectNoVisibleHistoryText(header: Locator) {
  await expect.poll(() => header.evaluate((node) => {
    const content = node.cloneNode(true) as HTMLElement;
    content.querySelectorAll(".sr-only").forEach((label) => label.remove());
    return content.textContent?.trim();
  })).toBe("");
}

test("wheel loading hands off to a retained 48px slot; prepend and delayed layout keep absolute reading coordinates", async ({ page }) => {
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  const header = page.locator(".thread-history-status");
  await expect(body).toBeVisible();
  await stableLayout(body);
  const nativeTop = await body.evaluate((node) => node.scrollTop);
  await body.hover();
  await page.mouse.wheel(0, -100);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeLessThan(nativeTop);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(0);
  const originalTop = await positionAtTop(body);
  await expect(header).not.toBeInViewport();
  await body.hover();
  await page.mouse.wheel(80, 0);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(0);
  for (const delta of [-100, -70, -45, -28, -16, -8, -3]) await page.mouse.wheel(0, delta);
  await expect(header).toHaveAttribute("data-state", "loading");
  await expect(header.locator(".thread-history-blocks")).toHaveCSS("color", "rgb(211, 94, 20)");
  await expect(header.locator(".thread-history-blocks > span").first()).not.toHaveCSS("animation-name", "none");
  expect(history.reads).toHaveLength(1);
  const held = await expectHeld(body, "Question 40");
  expect(held.anchorTop - originalTop).toBeCloseTo(48, 0);
  expect(held.headerTop).toBeCloseTo(held.frameTop, 0);
  await page.waitForTimeout(150);
  await expectCoordinates(body, "Question 40", held);
  await page.screenshot({ path: test.info().outputPath("history-loading-held.png") });

  // A programmatic scroll may clip the header, but must not retract its slot or spring.
  await body.evaluate((node) => { node.scrollTop = 12; });
  await stableLayout(body);
  const programmed = await historyGeometry(body, "Question 40");
  expectSameScroll(held, programmed, 12);
  expect(programmed.visibleHeight).toBeCloseTo(36, 0);
  expect(await displacement(body)).toBe(0);
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  await body.evaluate((node) => { node.scrollTop = 0; });
  await stableLayout(body);
  await expectCoordinates(body, "Question 40", held);

  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(header.locator(".thread-history-blocks > span").first()).toHaveCSS("animation-name", "none");
  await stableLayout(body);
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toHaveLength(1);

  await body.getByText("Question 28", { exact: true }).evaluate((node) => {
    const delayed = document.createElement("div");
    delayed.style.height = "160px";
    node.closest("[data-thread-display-unit]")!.prepend(delayed);
  });
  await stableLayout(body);
  await expectCoordinates(body, "Question 40", held);
  await page.screenshot({ path: test.info().outputPath("history-prepend-stable.png") });

  // Real forward scrolling transports header and messages together, not a pinned overlay.
  const beforeScroll = await body.evaluate((node) => node.scrollTop);
  await body.hover();
  await page.mouse.wheel(0, 16);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(beforeScroll);
  await stableLayout(body);
  const partial = await historyGeometry(body, "Question 40");
  const delta = await body.evaluate((node) => node.scrollTop) - beforeScroll;
  expectSameScroll(held, partial, delta);
  expect(partial.visibleHeight).toBeGreaterThan(0);
  expect(partial.visibleHeight).toBeLessThan(48);
  expect(await displacement(body)).toBe(0);
  await page.screenshot({ path: test.info().outputPath("history-native-scroll-clipped.png") });
  await page.mouse.wheel(0, 96);
  await expect(header).not.toBeInViewport();
  expect((await historyGeometry(body, "Question 40")).visibleHeight).toBe(0);
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  expect(history.reads).toHaveLength(1);
});

test("touch reveals a static partial ready header, arms only on release, and retains a stable full loading header", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
  const page = await context.newPage();
  const history = await installHistory(page);
  try {
    await page.goto("/browser/fixture.html?case=history-boundary");
    const body = page.getByTestId("thread-message-region");
    const header = page.locator(".thread-history-status");
    await expect(body).toBeVisible();
    await stableLayout(body);
    await positionAtTop(body);
    await expect(header).not.toBeInViewport();
    const cdp = await context.newCDPSession(page);
    const touch = async (type: "touchStart" | "touchMove" | "touchEnd", y = 200, x = 180) => cdp.send("Input.dispatchTouchEvent", {
      type, touchPoints: type === "touchEnd" ? [] : [{ x, y, id: 1 }],
    });
    await touch("touchStart");
    // Leftward tests horizontal intent without Chromium's native swipe-back gesture.
    await touch("touchMove", 210, 60);
    await touch("touchEnd");
    expect(await displacement(body)).toBe(0);
    expect(history.reads).toHaveLength(0);

    await touch("touchStart");
    await touch("touchMove", 240);
    const pulled = await displacement(body);
    const partial = await historyGeometry(body, "Question 40");
    expect(pulled).toBeGreaterThan(0);
    expect(pulled).toBeLessThan(80);
    expect(partial.visibleHeight).toBeGreaterThan(0);
    expect(partial.visibleHeight).toBeLessThan(partial.headerHeight);
    await expect(header).toHaveAttribute("data-state", "ready");
    await expect(header.locator(".thread-history-blocks > span").first()).toHaveCSS("animation-name", "none");
    expect(history.reads).toHaveLength(0);
    await page.screenshot({ path: test.info().outputPath("history-touch-partial-ready.png") });
    await touch("touchEnd");
    await expect.poll(() => displacement(body)).toBe(0);
    await expect(header).not.toBeInViewport();
    expect(history.reads).toHaveLength(0);

    await touch("touchStart");
    await touch("touchMove", 400);
    const armedDistance = await displacement(body);
    expect(armedDistance).toBeGreaterThanOrEqual(56);
    expect(armedDistance).toBeLessThan(80);
    await expect(header).toHaveAttribute("data-state", "ready");
    expect(history.reads).toHaveLength(0);
    await touch("touchEnd");
    await expect.poll(() => history.reads.length).toBe(1);
    await expect(header).toHaveAttribute("data-state", "loading");
    const held = await expectHeld(body, "Question 40");
    await page.waitForTimeout(150);
    await expectCoordinates(body, "Question 40", held);
    await page.screenshot({ path: test.info().outputPath("history-touch-held.png") });

    await touch("touchStart");
    await touch("touchMove", 240);
    await touch("touchEnd");
    await expectHeld(body, "Question 40");
    await expectCoordinates(body, "Question 40", held);
    expect(history.reads).toHaveLength(1);

    // Native finger-up movement must be free to scroll the retained header away.
    await touch("touchStart", 400);
    await touch("touchMove", 376);
    await touch("touchMove", 360);
    await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
    const scrolled = await historyGeometry(body, "Question 40");
    expectSameScroll(held, scrolled, await body.evaluate((node) => node.scrollTop));
    expect(scrolled.visibleHeight).toBeGreaterThan(0);
    expect(scrolled.visibleHeight).toBeLessThan(48);
    await touch("touchEnd");
    await page.getByRole("button", { name: "Switch conversation" }).click();
    await expect(body.getByText("Question 1", { exact: true })).toBeVisible();
    expect(await displacement(body)).toBe(0);
    await expect(body.locator(".thread-history-slot")).toHaveCount(0);
    history.complete();
    await page.waitForTimeout(100);
    await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  } finally { await context.close(); }
});

test("reduced-motion failure keeps its functional 48px slot and retry until naturally scrolled away", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" });
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary");
  await page.locator("html").evaluate((node) => node.classList.add("dark"));
  await expect(page.locator("main")).toHaveCSS("background-color", "rgb(48, 48, 48)");
  const body = page.getByTestId("thread-message-region");
  const header = page.locator(".thread-history-status");
  await expect(body).toBeVisible();
  await stableLayout(body);
  const originalTop = await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  const held = await expectHeld(body, "Question 40");
  expect(held.anchorTop - originalTop).toBeCloseTo(48, 0);
  const block = header.locator(".thread-history-blocks > span").first();
  await expect(block).toHaveCSS("background-color", "rgb(211, 94, 20)");
  await expect(block).toHaveCSS("animation-name", "none");
  history.complete("error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  await expect(retry).toBeInViewport();
  await page.waitForTimeout(150);
  await expectCoordinates(body, "Question 40", held);
  const failedBlocks = retry.locator(".thread-history-blocks");
  await expect(failedBlocks).toHaveCSS("width", "24px");
  await expect(failedBlocks).toHaveCSS("height", "24px");
  await expect(failedBlocks).toHaveCSS("color", "rgb(252, 165, 165)");
  await expect(failedBlocks.locator("span").first()).toHaveCSS("animation-name", "none");
  await expectNoVisibleHistoryText(header);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await failedBlocks.hover();
  await expect(page.getByRole("tooltip")).toHaveText("HTTP 503");
  await page.screenshot({ path: test.info().outputPath("history-failure-dark.png") });
  await page.mouse.move(16, 20, { steps: 5 });
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  await body.evaluate((node) => { node.scrollTop = 8; });
  await stableLayout(body);
  expectSameScroll(held, await historyGeometry(body, "Question 40"), 8);
  expect(await displacement(body)).toBe(0);
  await body.evaluate((node) => { node.scrollTop = 0; });
  await expectCoordinates(body, "Question 40", held);
  await body.hover();
  await page.mouse.wheel(0, 96);
  await expect(retry).not.toBeInViewport();
  await expect(header).toHaveAttribute("data-state", "error");
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  expect(history.reads).toHaveLength(1);
  await body.evaluate((node) => { node.scrollTop = 0; });
  await failedBlocks.click();
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(header).toHaveAttribute("data-state", "loading");
  await expect(header.locator(".thread-history-blocks")).toHaveCSS("width", "20px");
  await expect(block).toHaveCSS("animation-name", "none");
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await expectCoordinates(body, "Question 40", held);

  for (const [index, start] of [16, 4, 0].entries()) {
    await positionAtTop(body);
    await body.hover();
    await page.mouse.wheel(0, -120);
    await expect.poll(() => history.reads.length).toBe(index + 3);
    history.complete();
    await expect(body.getByText(`Question ${start}`, { exact: true })).toBeAttached();
  }
  await positionAtTop(body);
  const exhausted = page.locator('.thread-history-status[data-state="exhausted"]');
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect(exhausted).toBeInViewport();
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(5);
  await page.screenshot({ path: test.info().outputPath("history-exhausted-dark.png") });
  await expect(exhausted).toHaveCount(0);
});

test("fast responses retain static decorative Blocks; clicking them does not load, but the next boundary does", async ({ page }) => {
  const history = await installHistory(page);
  history.respondImmediately(true);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  const header = page.locator(".thread-history-status");
  await expect(body).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(header).not.toBeInViewport();
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  expect(history.reads).toHaveLength(1);
  await expect(header).toHaveAttribute("data-state", "ready");
  const held = await expectHeld(body, "Question 40");
  const blocks = header.locator(".thread-history-blocks");
  await expect(blocks).toBeInViewport();
  await expect(header.getByRole("button")).toHaveCount(0);
  await expectNoVisibleHistoryText(header);
  const block = blocks.locator("span").first();
  await expect(block).toHaveCSS("animation-name", "none");
  await expect(block).toHaveCSS("transform", "none");
  const box = (await blocks.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  // Wait past the shared 500ms tooltip delay: ready Blocks have no visible copy.
  await page.waitForTimeout(600);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await expectCoordinates(body, "Question 40", held);
  await page.screenshot({ path: test.info().outputPath("history-fast-ready.png") });

  history.respondImmediately(false);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await stableLayout(body);
  await expect(header).toHaveAttribute("data-state", "ready");
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toHaveLength(1);

  await positionAtTop(body);
  await stableLayout(body);
  const atNewHead = await historyGeometry(body, "Question 28");
  expect(atNewHead.firstKey).toBe("u28");
  expect(atNewHead.slotBeforeKey).toBe("u40");
  await expect(header).not.toBeInViewport();
  expect(history.reads).toHaveLength(1);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(header).toHaveAttribute("data-state", "loading");
  const nextHeld = await expectHeld(body, "Question 28");
  expect(nextHeld.slotBeforeKey).toBe("u28");
  expect(nextHeld.anchorTop - atNewHead.anchorTop).toBeCloseTo(48, 0);
  history.complete();
  await expect(body.getByText("Question 16", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(block).toHaveCSS("animation-name", "none");
  await stableLayout(body);
  await expectCoordinates(body, "Question 28", nextHeld);
  expect(history.reads).toEqual(["?limit=120&before=40", "?limit=120&before=28"]);
});

test("ordinary middle reading never reveals an exhausted overlay, even when the complete beginning is cached", async ({ page }) => {
  const history = await installHistory(page, 0, 52);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  const exhausted = page.getByText("No earlier messages", { exact: true });
  await expect(body.getByText("Question 51", { exact: true })).toBeAttached();
  await stableLayout(body);
  await expect(exhausted).toHaveCount(0);
  await body.evaluate((node) => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
    node.scrollTop = Math.round((node.scrollHeight - node.clientHeight) / 2);
  });
  await stableLayout(body);
  const middle = await body.evaluate((node) => node.scrollTop);
  expect(middle).toBeGreaterThan(48);
  expect(middle).toBeLessThan(await body.evaluate((node) => node.scrollHeight - node.clientHeight - 48));
  await expect(exhausted).toHaveCount(0);
  await body.hover();
  await page.mouse.wheel(0, -32);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeLessThan(middle);
  await expect(exhausted).toHaveCount(0);
  await page.mouse.wheel(0, 64);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(middle);
  await expect(exhausted).toHaveCount(0);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(0);
  await page.screenshot({ path: test.info().outputPath("history-middle-no-exhausted.png") });
});

test("a successful exhausted result belongs to its original inline slot and scrolls out, never floating over middle reading", async ({ page }) => {
  const history = await installHistory(page, 4);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  const exhausted = page.locator('.thread-history-status[data-state="exhausted"]');
  await expect(body).toBeVisible();
  await stableLayout(body);
  await expect(exhausted).toHaveCount(0);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  const held = await expectHeld(body, "Question 4");
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await expect(body.locator('.thread-history-slot .thread-history-status[data-state="exhausted"]')).toHaveCount(1);
  await expect(page.locator('.thread-viewport-frame > .thread-history-status[data-state="exhausted"]')).toHaveCount(0);
  await stableLayout(body);
  await expectCoordinates(body, "Question 4", held);
  const before = await historyGeometry(body, "Question 4");
  const beforeScroll = await body.evaluate((node) => node.scrollTop);
  await body.hover();
  await page.mouse.wheel(0, before.headerTop - before.frameTop + 16);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(beforeScroll);
  await stableLayout(body);
  const partial = await historyGeometry(body, "Question 4");
  expectSameScroll(before, partial, await body.evaluate((node) => node.scrollTop) - beforeScroll);
  expect(partial.visibleHeight).toBeGreaterThan(0);
  expect(partial.visibleHeight).toBeLessThan(48);
  await page.screenshot({ path: test.info().outputPath("history-exhausted-inline-clipped.png") });
  await page.mouse.wheel(0, 96);
  await expect(exhausted).not.toBeInViewport();
  expect((await historyGeometry(body, "Question 4")).visibleHeight).toBe(0);
  await page.mouse.wheel(0, 600);
  await stableLayout(body);
  await expect(exhausted).not.toBeInViewport();
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  expect(await displacement(body)).toBe(0);
  expect(history.reads).toHaveLength(1);
  await page.screenshot({ path: test.info().outputPath("history-exhausted-not-floating-in-middle.png") });
});

for (const reducedMotion of ["no-preference", "reduce"] as const) {
  test(`exhausted hints follow wheel and touch feedback, including settlement (${reducedMotion})`, async ({ page, browser, baseURL }) => {
    await page.emulateMedia({ reducedMotion });
    const reads = await installShortHistory(page);
    await page.goto("/browser/fixture.html?case=history-boundary");
    const body = page.getByTestId("thread-message-region");
    const hint = page.getByText("No earlier messages", { exact: true });
    await expect(body.getByText("Short answer.", { exact: true })).toBeVisible();
    await stableLayout(body);
    expect(await body.evaluate((node) => node.scrollHeight <= node.clientHeight)).toBe(true);
    await expect(hint).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath("exhausted-at-rest.png") });
    await body.hover();
    await page.mouse.wheel(80, 0);
    await expect(hint).toHaveCount(0);
    for (let attempt = 0; attempt < 2; attempt++) {
      await page.mouse.wheel(0, -120);
      await expect(hint).toBeVisible();
      if (reducedMotion === "reduce") expect(await displacement(body)).toBe(0);
      else await expect.poll(() => displacement(body)).toBeGreaterThan(0);
      if (attempt === 0) await page.screenshot({ path: test.info().outputPath("exhausted-wheel.png") });
      await expect(hint).toHaveCount(0);
      expect(await displacement(body)).toBe(0);
      expect(await body.evaluate((node) => node.scrollTop)).toBe(0);
    }
    expect(reads()).toBe(1);
    await page.reload();
    await expect(body.getByText("Short answer.", { exact: true })).toBeVisible();
    await expect(hint).toHaveCount(0);
    await body.hover();
    await page.mouse.wheel(0, -120);
    await expect(hint).toBeVisible();
    await page.getByRole("button", { name: "Switch conversation" }).click();
    await expect(hint).toHaveCount(0);
    expect(await displacement(body)).toBe(0);

    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion, baseURL });
    try {
      const touchPage = await context.newPage();
      const touchReads = await installShortHistory(touchPage);
      await touchPage.goto("/browser/fixture.html?case=history-boundary");
      const touchBody = touchPage.getByTestId("thread-message-region");
      const touchHint = touchPage.getByText("No earlier messages", { exact: true });
      await expect(touchBody.getByText("Short answer.", { exact: true })).toBeVisible();
      await stableLayout(touchBody);
      await expect(touchHint).toHaveCount(0);
      const cdp = await context.newCDPSession(touchPage);
      const touch = (type: "touchStart" | "touchMove" | "touchEnd", y = 200) => cdp.send("Input.dispatchTouchEvent", {
        type, touchPoints: type === "touchEnd" ? [] : [{ x: 180, y, id: 1 }],
      });
      await touch("touchStart");
      await touch("touchMove", 300);
      await expect(touchHint).toBeVisible();
      if (reducedMotion === "reduce") expect(await displacement(touchBody)).toBe(0);
      else expect(await displacement(touchBody)).toBeGreaterThan(0);
      await touchPage.screenshot({ path: test.info().outputPath("exhausted-touch.png") });
      await touch("touchEnd");
      await expect(touchHint).toHaveCount(0);
      expect(await displacement(touchBody)).toBe(0);
      expect(touchReads()).toBe(1);
    } finally { await context.close(); }
  });
}

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
    before: localAnchor, after: await anchorTop(body, "Cached message 160"),
  }), contentType: "application/json" });
  await expect(page.locator('.thread-history-status[data-state="exhausted"]')).toHaveCount(0);
  await positionAtTop(body);
  await expect(body.getByText("Cached message 0", { exact: true })).toBeAttached();
  await positionAtTop(body);
  const exhausted = page.locator('.thread-history-status[data-state="exhausted"]');
  await expect(exhausted).toHaveCount(0);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect(exhausted).toBeInViewport();
  await expect(exhausted).toHaveCount(0);
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
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  history.complete();
  await expect(body.getByText("Question 38", { exact: true })).toBeInViewport();
  await stableLayout(body);
  await body.hover();
  await page.mouse.wheel(0, 10000);
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  history.complete();
  await expect(body.getByText("Question 51", { exact: true })).toBeAttached();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  const held = await expectHeld(body, "Question 38");
  await page.mouse.wheel(0, -80);
  await stableLayout(body);
  expect(history.reads).toHaveLength(3);
  history.complete("error");
  await page.getByRole("button", { name: "Loading failed. Retry", exact: true }).click();
  await expect.poll(() => history.reads.length).toBe(4);
  history.complete();
  await expect(body.getByText("Question 26", { exact: true })).toBeAttached();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(page.locator('.thread-history-status[data-state="ready"]')).toBeInViewport();
  await stableLayout(body);
  await expectCoordinates(body, "Question 38", held);
  await positionAtTop(body);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(page.locator('.thread-history-status[data-state="ready"] .thread-history-blocks > span').first()).toHaveCSS("animation-name", "none");
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&after=50", "?limit=24&before=38", "?limit=24&before=38"]);
});

async function jumpViaRail(page: Page, index: number) {
  const rail = page.getByTestId("prompt-rail-scroll");
  await expect(rail).toBeVisible();
  await rail.getByRole("button").first().focus();
  await page.keyboard.press(index < 26 ? "Home" : "End");
  await rail.getByRole("button", { name: `Jump to message: Question ${index}`, exact: true }).click();
}

test("failed Blocks animate without visible error text; pulling retries once and pending input cannot duplicate the request", async ({ page }) => {
  const history = await installHistory(page);
  await page.goto("/browser/fixture.html?case=history-boundary");
  const body = page.getByTestId("thread-message-region");
  const header = page.locator(".thread-history-status");
  const slot = body.locator(".thread-history-slot");
  await expect(body).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  const held = await expectHeld(body, "Question 40");
  expect(held.slotBeforeKey).toBe("u40");
  history.complete("error");
  await expect(header).toHaveAttribute("data-state", "error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  const blocks = retry.locator(".thread-history-blocks");
  await expect(blocks).toBeInViewport();
  await expect(blocks).toHaveCSS("color", "rgb(185, 28, 28)");
  await expect(blocks.locator("span").first()).not.toHaveCSS("animation-name", "none");
  await expectNoVisibleHistoryText(header);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await stableLayout(body);
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toHaveLength(1);

  // This is a fresh pull at the failed boundary, not a ready-button-only path.
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(header).toHaveAttribute("data-state", "loading");
  await page.mouse.wheel(0, -120);
  await page.mouse.wheel(0, -80);
  await body.evaluate((node) => { node.tabIndex = 0; node.focus({ preventScroll: true }); });
  await page.keyboard.press("ArrowUp");
  await stableLayout(body);
  await expect(slot).toHaveCSS("height", "48px");
  await expect.poll(() => displacement(body)).toBe(0);
  expect((await historyGeometry(body, "Question 40")).slotBeforeKey).toBe("u40");
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toEqual(["?limit=120&before=40", "?limit=120&before=40"]);

  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(blocks).toHaveCount(0);
  await stableLayout(body);
  await expect(slot).toHaveCSS("height", "48px");
  expect((await historyGeometry(body, "Question 40")).slotBeforeKey).toBe("u40");
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toHaveLength(2);
});

test("cross-path unloaded rail jump has visible navigation feedback outside a scrolled-away older slot", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser/fixture.html?case=history-boundary&navigate=1");
  const body = page.getByTestId("thread-message-region");
  const slot = body.locator(".thread-history-slot");
  await expect(body).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expectHeld(body, "Question 40");
  await body.hover();
  await page.mouse.wheel(0, 128);
  await expect(slot.locator(".thread-history-status")).not.toBeInViewport();
  await expect(slot).toHaveCSS("height", "48px");
  // Start the replacement away from the old bottom so setup cannot prefetch newer.
  await positionAtTop(body);
  await stableLayout(body);
  await expect(slot.locator(".thread-history-status")).not.toBeInViewport();

  await jumpViaRail(page, 10);
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  await expect(slot.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  history.complete("error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  await expect(retry).toBeInViewport();
  await expect(slot.locator('.thread-history-status[data-state="error"]')).toHaveCount(0);
  await retry.click();
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  expect(history.reads).toEqual(["?limit=120&before=40", "?limit=24&after=10", "?limit=24&after=10"]);
  history.complete();
  await expect(body.getByText("Question 10", { exact: true })).toBeInViewport();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(retry).toHaveCount(0);
});

test("cross-path newer has visible navigation feedback and forward input retries newer after its older slot scrolls away", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser/fixture.html?case=history-boundary&navigate=1");
  const body = page.getByTestId("thread-message-region");
  const slot = body.locator(".thread-history-slot");
  await expect(body).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await stableLayout(body);
  await jumpViaRail(page, 10);
  await expect.poll(() => history.reads.length).toBe(1);
  history.complete();
  await expect(body.getByText("Question 10", { exact: true })).toBeInViewport();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(2);
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await expect(slot).toHaveCSS("height", "48px");
  await expect.poll(() => displacement(body)).toBe(0);
  await expect(slot.locator(".thread-history-status")).toBeInViewport();
  await body.hover();
  await page.mouse.wheel(0, 128);
  await expect(slot.locator(".thread-history-status")).not.toBeInViewport();
  await expect(slot).toHaveCSS("height", "48px");
  await page.mouse.wheel(0, 10000);
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  await expect(slot.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  history.complete("error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  await expect(retry).toBeInViewport();
  await expect(slot.locator('.thread-history-status[data-state="error"]')).toHaveCount(0);
  await stableLayout(body);
  expect(history.reads).toHaveLength(3);
  await body.hover();
  await page.mouse.wheel(0, 120);
  await expect.poll(() => history.reads.length).toBe(4);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  expect(history.reads).toEqual(["?limit=24&after=10", "?limit=24&before=10", "?limit=24&after=22", "?limit=24&after=22"]);
  history.complete();
  await expect(body.getByText("Question 33", { exact: true })).toBeAttached();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(retry).toHaveCount(0);
});

test("cross-path older errors never float after latest or a loaded rail jump, but boundary retry remains available", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const body = page.getByTestId("thread-message-region");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  for (const destination of ["latest", "loaded prompt"] as const) {
    await test.step(destination, async () => {
      const initialReads = history.reads.length;
      await page.goto("/browser/fixture.html?case=history-boundary&navigate=1");
      await expect(body).toBeVisible();
      await stableLayout(body);
      await positionAtTop(body);
      await body.hover();
      await page.mouse.wheel(0, -120);
      await expect.poll(() => history.reads.length).toBe(initialReads + 1);
      history.complete("error");
      await expect(retry).toBeInViewport();
      await expectHeld(body, "Question 40");

      if (destination === "latest") {
        await page.getByRole("button", { name: "Scroll to bottom", exact: true }).click();
        await expect(body.getByText("Question 51", { exact: true })).toBeInViewport();
      } else {
        await jumpViaRail(page, 46);
        await expect(body.getByText("Question 46", { exact: true })).toBeInViewport();
      }
      await stableLayout(body);
      await expect.soft(page.locator('.thread-viewport-frame > .thread-history-status[data-state="error"]')).toHaveCount(0, { timeout: 1000 });
      await expect.soft(retry).not.toBeInViewport({ timeout: 1000 });
      await body.hover();
      await page.mouse.wheel(0, -64);
      await stableLayout(body);
      await expect.soft(retry).not.toBeInViewport({ timeout: 1000 });
      expect(history.reads).toHaveLength(initialReads + 1);

      await positionAtTop(body);
      await retry.focus();
      await expect(retry).toBeInViewport();
      expect(history.reads).toHaveLength(initialReads + 1);
      await retry.click();
      await expect.poll(() => history.reads.length).toBe(initialReads + 2);
      expect(history.reads.slice(initialReads)).toEqual(["?limit=120&before=40", "?limit=120&before=40"]);
      history.complete();
      await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
      await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
      await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
    });
  }
});


test("bounded navigation retains three pages and preserves each new wheel or keyboard boundary slot through completion", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser/fixture.html?case=history-boundary&navigate=1");
  const body = page.getByTestId("thread-message-region");
  const header = page.locator(".thread-history-status");
  const slot = body.locator(".thread-history-slot");
  const approachNextHead = async (text: string) => {
    // Real scrolling stops just short of the boundary, before it can request.
    const scrollTop = await body.evaluate((node) => node.scrollTop);
    expect(scrollTop).toBeGreaterThan(120);
    await body.hover();
    await page.mouse.wheel(0, 120 - scrollTop);
    await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeCloseTo(120, 0);
    await stableLayout(body);
    await expect(header).not.toBeInViewport();
    return historyGeometry(body, text);
  };
  await expect(body.getByText("Question 40", { exact: true })).toBeAttached();
  await expect(body.getByText("Question 38", { exact: true })).toHaveCount(0);
  await stableLayout(body);
  // Keep the replacement away from latest's bottom so setup cannot prefetch newer.
  await positionAtTop(body);
  await stableLayout(body);
  expect(history.reads).toHaveLength(0);

  // An unloaded rail destination replaces latest with P0 (38..49).
  await jumpViaRail(page, 38);
  await expect.poll(() => history.reads.length).toBe(1);
  history.complete();
  await expect(body.getByText("Question 38", { exact: true })).toBeInViewport();
  await expect(body.getByText("Question 49", { exact: true })).toBeAttached();
  await stableLayout(body);
  await positionAtTop(body);
  await body.hover();
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(2);
  await expect(header).toHaveAttribute("data-state", "loading");
  const held = await expectHeld(body, "Question 38");
  expect(held.slotBeforeKey).toBe("u38");

  history.complete();
  await expect(body.getByText("Question 26", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await stableLayout(body);
  await expectCoordinates(body, "Question 38", held);
  expect((await historyGeometry(body, "Question 38")).slotBeforeKey).toBe("u38");
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(24);

  // Reach each prepended page head instead of loading from the old reading slot.
  const atSecondHead = await approachNextHead("Question 26");
  expect(atSecondHead.firstKey).toBe("u26");
  expect(atSecondHead.slotBeforeKey).toBe("u38");
  expect(history.reads).toHaveLength(2);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(header).toHaveAttribute("data-state", "loading");
  const secondHeld = await expectHeld(body, "Question 26");
  expect(secondHeld.slotBeforeKey).toBe("u26");
  expect(secondHeld.anchorTop - atSecondHead.anchorTop - atSecondHead.scrollTop).toBeCloseTo(48, 0);
  history.complete();
  await expect(body.getByText("Question 14", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await stableLayout(body);
  await expectCoordinates(body, "Question 26", secondHeld);
  expect((await historyGeometry(body, "Question 26")).slotBeforeKey).toBe("u26");
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(36);

  // Even with three pages retained, decorative Blocks cannot request or evict.
  const blocks = header.locator(".thread-history-blocks");
  await expect(blocks).toBeInViewport();
  await expect(blocks.locator("span").first()).toHaveCSS("animation-name", "none");
  await expect(header.getByRole("button")).toHaveCount(0);
  await expectNoVisibleHistoryText(header);
  const box = (await blocks.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await stableLayout(body);
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(page.getByText("No earlier messages", { exact: true })).toHaveCount(0);
  await expect(slot).toHaveCSS("height", "48px");
  await expectCoordinates(body, "Question 26", secondHeld);
  expect((await historyGeometry(body, "Question 26")).slotBeforeKey).toBe("u26");
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26"]);

  const atNewHead = await approachNextHead("Question 14");
  expect(atNewHead.firstKey).toBe("u14");
  expect(atNewHead.slotBeforeKey).toBe("u26");
  expect(history.reads).toHaveLength(3);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(4);
  await expect(header).toHaveAttribute("data-state", "loading");
  const newHeld = await expectHeld(body, "Question 14");
  expect(newHeld.slotBeforeKey).toBe("u14");
  expect(newHeld.anchorTop - atNewHead.anchorTop - atNewHead.scrollTop).toBeCloseTo(48, 0);
  history.complete();
  await expect(body.getByText("Question 2", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "ready");
  await stableLayout(body);
  await expectCoordinates(body, "Question 14", newHeld);
  await expect(slot).toHaveCSS("height", "48px");
  const completed = await historyGeometry(body, "Question 14");
  expect(completed.slotBeforeKey).toBe("u14");
  expect(completed.firstKey).toBe("u2");
  await expect(body.getByText("Question 37", { exact: true })).toBeAttached();
  await expect(body.getByText("Question 38", { exact: true })).toHaveCount(0);
  await expect(body.getByText("Question 49", { exact: true })).toHaveCount(0);
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(36);
  await expectNoVisibleHistoryText(header);
  await expect(header.getByRole("button")).toHaveCount(0);
  await expect(page.getByText("No earlier messages", { exact: true })).toHaveCount(0);
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26", "?limit=24&before=14"]);

  // A real Home key reaches the next boundary and rebinds without a wheel pull.
  const atKeyboardHead = await approachNextHead("Question 2");
  expect(atKeyboardHead.firstKey).toBe("u2");
  expect(atKeyboardHead.slotBeforeKey).toBe("u14");
  await body.evaluate((node) => { node.tabIndex = 0; node.focus({ preventScroll: true }); });
  expect(history.reads).toHaveLength(4);
  await page.keyboard.press("Home");
  await expect.poll(() => history.reads.length).toBe(5);
  await expect(header).toHaveAttribute("data-state", "loading");
  const keyboardHeld = await expectHeld(body, "Question 2");
  expect(keyboardHeld.slotBeforeKey).toBe("u2");
  expect(keyboardHeld.anchorTop - atKeyboardHead.anchorTop - atKeyboardHead.scrollTop).toBeCloseTo(48, 0);
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await expect(header).toHaveAttribute("data-state", "exhausted");
  await stableLayout(body);
  await expectCoordinates(body, "Question 2", keyboardHeld);
  await expect(slot).toHaveCSS("height", "48px");
  const keyboardCompleted = await historyGeometry(body, "Question 2");
  expect(keyboardCompleted.slotBeforeKey).toBe("u2");
  expect(keyboardCompleted.firstKey).toBe("u0");
  await expect(body.getByText("Question 25", { exact: true })).toBeAttached();
  await expect(body.getByText("Question 26", { exact: true })).toHaveCount(0);
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(26);
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26", "?limit=24&before=14", "?limit=24&before=2"]);
});
