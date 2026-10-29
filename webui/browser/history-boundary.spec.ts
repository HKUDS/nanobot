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
  let fastResponse = false;
  let releaseFastResponse: (() => void) | null = null;
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
    const outcome = fastResponse
      ? await new Promise<"success">((resolve) => { releaseFastResponse = () => resolve("success"); })
      : await new Promise<"success" | "error">((resolve) => pending.push(resolve));
    if (outcome === "error") return route.fulfill({ status: 503, body: "History unavailable" });
    const start = url.searchParams.has("after") ? Number(cursor) : Math.max(0, Number(cursor) - 12);
    const count = url.searchParams.has("after") ? 12 : Number(cursor) - start;
    await route.fulfill({ json: historyPage(start, count, start > 0) });
  });
  return {
    reads,
    useFastResponse: (value: boolean) => { fastResponse = value; },
    releaseFastResponse: () => { releaseFastResponse?.(); releaseFastResponse = null; },
    complete: (outcome: "success" | "error" = "success") => pending.shift()?.(outcome),
  };
}

type HistoryFixture = Awaited<ReturnType<typeof installHistory>>;

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
    const frame = node.closest<HTMLElement>(".thread-viewport-frame")!;
    const header = node.closest(".thread-viewport")!.querySelector<HTMLElement>(".thread-history-status");
    const first = node.querySelector<HTMLElement>("[data-thread-display-unit]");
    let previous: number[] | null = null;
    let stable = 0;
    for (let i = 0; i < 240 && stable < 8; i++) {
      await new Promise(requestAnimationFrame);
      const rect = (element: HTMLElement | null) => {
        const box = element?.getBoundingClientRect();
        return [box?.top ?? 0, box?.bottom ?? 0];
      };
      const transform = new DOMMatrix(getComputedStyle(node).transform).m42;
      const value = [node.scrollHeight, node.scrollTop, transform, ...rect(frame), ...rect(header), ...rect(first)];
      stable = previous && value.every((coordinate, index) => Math.abs(coordinate - previous![index]!) < 0.01)
        ? stable + 1 : 0;
      previous = value;
    }
    if (stable < 8) throw new Error("Thread history layout did not settle across frame and anchor geometry");
  });
}

async function anchorTop(body: Locator, text: string) {
  return body.getByText(text, { exact: true }).evaluate((node) =>
    node.closest("[data-thread-display-unit]")!.getBoundingClientRect().top);
}

async function openSettledHistory(page: Page, query = "") {
  await page.goto(`/browser/fixture.html?case=history-boundary${query}`);
  const body = page.getByTestId("thread-message-region");
  await expect(body).toBeVisible();
  await stableLayout(body);
  return { body, header: page.locator(".thread-history-status"), slot: body.locator(".thread-history-slot") };
}

async function requestOlderWithWheel(body: Locator, history: HistoryFixture, readCount: number) {
  await body.hover();
  await body.page().mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(readCount);
}

async function positionReadingAnchor(body: Locator, text: string) {
  await body.getByText(text, { exact: true }).evaluate((node) => {
    const unit = node.closest("[data-thread-display-unit]")!;
    const scroller = unit.closest<HTMLElement>(".thread-message-viewport")!;
    scroller.scrollTop += unit.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 280;
  });
  await stableLayout(body);
  return anchorTop(body, text);
}

async function completePrepend(history: HistoryFixture, body: Locator, firstText: string, anchorText: string, expectedTop: number) {
  history.complete();
  await expect(body.getByText(firstText, { exact: true })).toBeAttached();
  await expect(body.page().locator(".thread-history-status")).toHaveCount(0);
  await stableLayout(body);
  await expectAnchorCoordinate(body, anchorText, expectedTop);
}

async function themeColor(locator: Locator, token: "--muted-foreground" | "--destructive") {
  return locator.evaluate((node, variable) => {
    const probe = document.createElement("span");
    probe.style.color = `hsl(var(${variable}))`;
    node.append(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  }, token);
}

// Use the fixed viewport, never the transformed scroller, as the coordinate frame.
async function historyGeometry(body: Locator, text: string) {
  return body.getByText(text, { exact: true }).evaluate((node) => {
    const unit = node.closest("[data-thread-display-unit]")!.getBoundingClientRect();
    const frame = node.closest(".thread-viewport-frame")!.getBoundingClientRect();
    const scroller = node.closest<HTMLElement>(".thread-message-viewport")!;
    const header = node.closest(".thread-viewport")!.querySelector(".thread-history-status")?.getBoundingClientRect();
    const slot = scroller.querySelector(".thread-history-slot");
    return {
      headerTop: header?.top ?? 0, headerBottom: header?.bottom ?? 0, headerHeight: header?.height ?? 0,
      visibleHeight: header ? Math.max(0, Math.min(header.bottom, frame.bottom) - Math.max(header.top, frame.top)) : 0,
      anchorTop: unit.top, frameTop: frame.top, scrollTop: scroller.scrollTop,
      transformY: new DOMMatrix(getComputedStyle(scroller).transform).m42,
      slotHeight: slot ? Number.parseFloat(getComputedStyle(slot).height) : 0,
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

async function expectHeaderInsideSlot(body: Locator) {
  const geometry = await body.locator(".thread-history-slot").evaluate((slot) => {
    const header = slot.querySelector(".thread-history-status")!.getBoundingClientRect();
    const own = slot.getBoundingClientRect();
    const before = slot.parentElement!.previousElementSibling?.getBoundingClientRect();
    const after = slot.parentElement!.nextElementSibling!.getBoundingClientRect();
    return { headerTop: header.top, headerBottom: header.bottom, slotTop: own.top, slotBottom: own.bottom,
      previousBottom: before?.bottom, nextTop: after.top };
  });
  expect(Math.abs(geometry.headerTop - geometry.slotTop)).toBeLessThan(1);
  expect(Math.abs(geometry.headerBottom - geometry.slotBottom)).toBeLessThan(1);
  if (geometry.previousBottom !== undefined) expect(geometry.previousBottom).toBeLessThanOrEqual(geometry.headerTop);
  expect(geometry.headerBottom).toBeLessThanOrEqual(geometry.nextTop);
}

async function expectHeld(body: Locator, text: string) {
  await expect(body.locator(".thread-history-slot")).toHaveCSS("height", "48px");
  await expect.poll(() => displacement(body)).toBe(0);
  let held = await historyGeometry(body, text);
  // The runtime accepts <=1px as the top; account for that actual scroll, not extra clipping.
  await expect.poll(async () => {
    held = await historyGeometry(body, text);
    return held.visibleHeight + held.scrollTop;
  }).toBeCloseTo(48, 0);
  expect(held.scrollTop).toBeGreaterThanOrEqual(0);
  expect(held.scrollTop).toBeLessThanOrEqual(1);
  await expectHeaderInsideSlot(body);
  return held;
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
  const { body, header } = await openSettledHistory(page);
  const nativeTop = await body.evaluate((node) => node.scrollTop);
  await body.hover();
  // Lazy Markdown can change scrollTop before the queued wheel reaches the viewport.
  const wheelDelivered = await body.evaluateHandle((node) => ({
    done: new Promise<void>((resolve) => node.addEventListener("wheel", () => resolve(), { once: true })),
  }));
  await page.mouse.wheel(0, -100);
  await wheelDelivered.evaluate(({ done }) => done);
  await wheelDelivered.dispose();
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
  await expect(header.locator(".thread-history-blocks")).toHaveCSS("color", "rgb(98, 98, 106)");
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
  const preCompletionAnchorTop = await positionReadingAnchor(body, "Question 40");

  await completePrepend(history, body, "Question 28", "Question 40", preCompletionAnchorTop);
  const completedSpacing = await historyBoundarySpacing(body, "Question 40", "Question 41");
  const completedAnchorTop = await anchorTop(body, "Question 40");
  console.log("history-completion-spacing", JSON.stringify({ ...completedSpacing, readingDeltaPx: completedAnchorTop - preCompletionAnchorTop }));
  expect(Math.abs(completedSpacing.boundaryGap! - completedSpacing.referenceGap!), JSON.stringify(completedSpacing)).toBeLessThan(1);
  expect(completedSpacing.slotCount).toBe(0);
  expect(history.reads).toHaveLength(1);

  await body.getByText("Question 28", { exact: true }).evaluate((node) => {
    const delayed = document.createElement("div");
    delayed.style.height = "160px";
    node.closest("[data-thread-display-unit]")!.prepend(delayed);
  });
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 40", preCompletionAnchorTop);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("history-prepend-stable.png") });

  // The reclaimed boundary scrolls as ordinary message flow, with no retained spacer.
  const beforeScroll = await body.evaluate((node) => node.scrollTop);
  const anchorBeforeScroll = await anchorTop(body, "Question 40");
  await body.hover();
  await page.mouse.wheel(0, 16);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeGreaterThan(beforeScroll);
  await stableLayout(body);
  const delta = await body.evaluate((node) => node.scrollTop) - beforeScroll;
  expect(Math.abs((await anchorTop(body, "Question 40")) - anchorBeforeScroll + delta)).toBeLessThan(1);
  expect(await displacement(body)).toBe(0);
  await page.screenshot({ path: test.info().outputPath("history-native-scroll-reclaimed.png") });
  await page.mouse.wheel(0, 96);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  expect(history.reads).toHaveLength(1);
});

test("archived task results stay with the retained boundary when earlier messages load", async ({ page }) => {
  const history = await installHistory(page);
  await page.route("**/api/sessions/**/subagents", (route) => route.fulfill({ json: { tasks: [{
    task_id: "legacy", revision: 1, label: "Earlier check", task_description: "Check earlier work",
    state: "done", phase: "completed", elapsed_seconds: 2, iteration: 1,
    tool_events: [], usage: null, receipts: {}, result: "Verified", partial: false,
    stop_reason: null, error: null, origin_turn_id: "legacy-turn", origin_message_id: null,
    created_at: 100, completed_at: 102,
  }] } }));
  await page.goto("/browser/fixture.html?case=history-boundary&tasks");
  const body = page.getByTestId("thread-message-region");
  const otherTasks = body.getByRole("region", { name: "Other tasks" });
  await expect(otherTasks).toBeAttached();
  // Clicking an offscreen disclosure scrolls it into view and can prefetch history.
  await positionAtTop(body);
  await otherTasks.getByRole("button", { name: /Other tasks/ }).click();
  await expect(otherTasks.getByRole("button", { name: /Earlier check Completed/ })).toBeVisible();
  await stableLayout(body);
  const originalTop = await positionAtTop(body);
  await body.hover();
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  expect(history.reads).toHaveLength(0);
  await page.mouse.wheel(0, -100);
  await expect(page.locator(".thread-history-status")).toHaveAttribute("data-state", "loading");
  const held = await expectHeld(body, "Question 40");
  expect(held.anchorTop - originalTop).toBeCloseTo(48, 0);
  const preCompletionAnchorTop = await positionReadingAnchor(body, "Question 40");
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(page.locator(".thread-history-slot")).toHaveCount(0);
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 40", preCompletionAnchorTop);
  await expect(otherTasks).toHaveCount(1);
  await expect(otherTasks.getByRole("button", { name: /Other tasks/ })).toHaveAttribute("aria-expanded", "true");
  expect(history.reads).toHaveLength(1);
});

test("touch reveals a static partial ready header, arms only on release, and retains a stable full loading header", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
  const page = await context.newPage();
  const history = await installHistory(page);
  try {
    const { body, header } = await openSettledHistory(page);
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
    console.log("history-touch-native-scroll", JSON.stringify({ held, scrolled }));
    expectSameScroll(held, scrolled, scrolled.scrollTop);
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

for (const replacement of ["before move", "before release", "before cancel"] as const) {
  test(`history touch continues when the touched message is replaced ${replacement}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
    const page = await context.newPage();
    const history = await installHistory(page);
    let allowRenderer = () => {};
    let rendererRequested = () => {};
    const rendererGate = new Promise<void>((resolve) => { allowRenderer = resolve; });
    const requested = new Promise<void>((resolve) => { rendererRequested = resolve; });
    await page.route("**/src/components/MarkdownTextRenderer.tsx*", async (route) => {
      rendererRequested();
      await rendererGate;
      await route.continue();
    });
    try {
      const { body, header } = await openSettledHistory(page);
      await positionAtTop(body);
      await stableLayout(body);
      await requested;
      const fallback = body.locator('[data-assistant-selectable="true"] > .whitespace-pre-wrap:visible').first();
      await expect(fallback).toBeVisible();
      await expect(fallback).toContainText("Historical answer.");
      const target = await fallback.elementHandle();
      const box = await target?.boundingBox();
      if (!target || !box) throw new Error("The Markdown fallback must be visible before the touch gesture");
      const x = box.x + Math.min(50, box.width / 2), y = box.y + Math.min(10, box.height / 2);
      expect(await target.evaluate((node, point) => document.elementFromPoint(point.x, point.y) === node, { x, y })).toBe(true);
      const cdp = await context.newCDPSession(page);
      const touch = (type: "touchStart" | "touchMove" | "touchEnd" | "touchCancel", touchY = y) => cdp.send("Input.dispatchTouchEvent", {
        type, touchPoints: type === "touchEnd" || type === "touchCancel" ? [] : [{ x, y: touchY, id: 1 }],
      });
      await touch("touchStart");
      if (replacement !== "before move") {
        await touch("touchMove", y + (replacement === "before cancel" ? 200 : 40));
        if (replacement === "before cancel") expect(await displacement(body)).toBeGreaterThanOrEqual(56);
        else expect(await displacement(body)).toBeGreaterThan(0);
        expect(history.reads).toHaveLength(0);
      }
      allowRenderer();
      await expect.poll(() => target.evaluate((node) => node?.isConnected)).toBe(false);
      if (replacement === "before move") {
        await touch("touchMove", y + 200);
        expect(await displacement(body)).toBeGreaterThanOrEqual(56);
        expect(history.reads).toHaveLength(0);
      }
      await touch(replacement === "before cancel" ? "touchCancel" : "touchEnd");
      if (replacement !== "before move") {
        await expect.poll(() => displacement(body)).toBe(0);
        await expect(header).not.toBeInViewport();
        expect(history.reads).toHaveLength(0);
      }
      if (replacement === "before cancel") {
        // Cancellation must not leave a stale gesture that prevents the next pull.
        await touch("touchStart");
        await touch("touchMove", y + 200);
        expect(await displacement(body)).toBeGreaterThanOrEqual(56);
        expect(history.reads).toHaveLength(0);
        await touch("touchEnd");
      }
      if (replacement !== "before release") {
        await expect.poll(() => history.reads.length).toBe(1);
        await expect(header).toHaveAttribute("data-state", "loading");
        history.complete();
      }
      await target.dispose();
    } finally {
      allowRenderer();
      await context.close();
    }
  });
}

test("a second finger cancels an active history pull without loading", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
  const page = await context.newPage();
  const history = await installHistory(page);
  try {
    const { body, header } = await openSettledHistory(page);
    await positionAtTop(body);
    const cdp = await context.newCDPSession(page);
    const dispatch = (type: "touchStart" | "touchMove" | "touchEnd", touchPoints: { id: number; x: number; y: number }[]) =>
      cdp.send("Input.dispatchTouchEvent", { type, touchPoints });
    await dispatch("touchStart", [{ id: 1, x: 180, y: 200 }]);
    await dispatch("touchMove", [{ id: 1, x: 180, y: 240 }]);
    expect(await displacement(body)).toBeGreaterThan(0);
    await dispatch("touchStart", [{ id: 1, x: 180, y: 240 }, { id: 2, x: 220, y: 240 }]);
    await expect.poll(() => displacement(body)).toBe(0);
    await expect(header).not.toBeInViewport();
    expect(history.reads).toHaveLength(0);
    await dispatch("touchEnd", []);
    await dispatch("touchStart", [{ id: 1, x: 180, y: 200 }]);
    await dispatch("touchMove", [{ id: 1, x: 180, y: 400 }]);
    expect(await displacement(body)).toBeGreaterThanOrEqual(56);
    await dispatch("touchEnd", []);
    await expect.poll(() => history.reads.length).toBe(1);
    history.complete();
  } finally { await context.close(); }
});

test("switching conversations cancels an in-progress history pull", async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL });
  const page = await context.newPage();
  const history = await installHistory(page);
  try {
    const { body } = await openSettledHistory(page);
    await positionAtTop(body);
    const cdp = await context.newCDPSession(page);
    const touch = (type: "touchStart" | "touchMove" | "touchEnd", y = 200) => cdp.send("Input.dispatchTouchEvent", {
      type, touchPoints: type === "touchEnd" ? [] : [{ id: 1, x: 180, y }],
    });
    await touch("touchStart");
    await touch("touchMove", 240);
    expect(await displacement(body)).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Switch conversation" }).click();
    await expect(body.getByText("Question 1", { exact: true })).toBeVisible();
    await touch("touchEnd");
    await expect.poll(() => displacement(body)).toBe(0);
    expect(history.reads).toHaveLength(0);
    await page.getByRole("button", { name: "Switch conversation" }).click();
    await expect(body.getByText("Question 40", { exact: true })).toBeVisible();
    await positionAtTop(body);
    await touch("touchStart");
    await touch("touchMove", 400);
    expect(await displacement(body)).toBeGreaterThanOrEqual(56);
    await touch("touchEnd");
    await expect.poll(() => history.reads.length).toBe(1);
    history.complete();
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
  await requestOlderWithWheel(body, history, 1);
  const held = await expectHeld(body, "Question 40");
  expect(held.anchorTop - originalTop).toBeCloseTo(48, 0);
  const block = header.locator(".thread-history-blocks > span").first();
  const normalColor = await header.locator(".thread-history-blocks").evaluate((node) => getComputedStyle(node).color);
  const mutedColor = await themeColor(header, "--muted-foreground");
  expect(normalColor).toBe(mutedColor);
  console.log(`history-colors dark loading=${normalColor}`);
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
  await expectHeaderInsideSlot(body);
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
  await expect(header).toHaveCount(0);
  await expectAnchorCoordinate(body, "Question 40", held.anchorTop);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);

  for (const [index, start] of [16, 4, 0].entries()) {
    await positionAtTop(body);
    await requestOlderWithWheel(body, history, index + 3);
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

test("keeps the reading anchor when lazy Markdown loads after a fast prepend", async ({ page }) => {
  let releaseMarkdown = () => {};
  const ready = new Promise<void>((resolve) => { releaseMarkdown = resolve; });
  await page.route("**/MarkdownTextRenderer.tsx*", async (route) => {
    await ready;
    await route.continue();
  });
  const history = await installHistory(page);
  history.useFastResponse(true);
  await page.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
  const { body, header } = await openSettledHistory(page);
  await positionAtTop(body);
  await body.hover();
  await page.clock.pauseAt(new Date("2026-01-01T01:00:00Z"));
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  await expect(header).toHaveAttribute("data-state", "loading");
  const readingTop = await anchorTop(body, "Question 40");
  history.releaseFastResponse();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expectAnchorCoordinate(body, "Question 40", readingTop);

  releaseMarkdown();
  await page.clock.resume();
  await expect(body.locator('[data-thread-display-unit="a40"] p')).toHaveCount(8);
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 40", readingTop);
});

for (const elapsedMs of [0, 80]) test(`fast responses reclaim completed slots and keep the next boundary loading${elapsedMs ? " during spring travel" : ""}`, async ({ page }) => {
  const history = await installHistory(page);
  history.useFastResponse(true);
  await page.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
  const { body, header } = await openSettledHistory(page);
  // The lazy plain-text fallback has a different height; measure the spring only after Markdown loads.
  await expect(body.getByText("Historical answer.", { exact: true }).first()).toBeVisible();
  await stableLayout(body);
  await positionAtTop(body);
  await expect(header).toHaveAttribute("data-state", "ready");
  await expect(header).not.toBeInViewport();
  await body.hover();
  await page.clock.pauseAt(new Date("2026-01-01T01:00:00Z"));
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(1);
  await expect(header).toHaveAttribute("data-state", "loading");
  if (elapsedMs > 0) await page.clock.runFor(elapsedMs);
  const beforeFastRead = await historyGeometry(body, "Question 40");
  expect(beforeFastRead.slotHeight).toBe(48);
  expect(Math.abs(beforeFastRead.transformY)).toBeGreaterThan(0);
  if (elapsedMs > 0) expect(beforeFastRead.transformY).toBeGreaterThan(-48);
  history.releaseFastResponse();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  expect(history.reads).toHaveLength(1);
  await expect(header).toHaveCount(0);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  const afterFastRead = await historyGeometry(body, "Question 40");
  console.log("history-fast-completion-geometry", JSON.stringify({ before: beforeFastRead, after: afterFastRead }));
  await expectAnchorCoordinate(body, "Question 40", beforeFastRead.anchorTop);
  const fastSpacing = await historyBoundarySpacing(body, "Question 40", "Question 41");
  expect(Math.abs(fastSpacing.boundaryGap! - fastSpacing.referenceGap!)).toBeLessThan(1);
  await page.clock.resume();
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 40", beforeFastRead.anchorTop);
  const settledFastSpacing = await historyBoundarySpacing(body, "Question 40", "Question 41");
  expect(Math.abs(settledFastSpacing.boundaryGap! - settledFastSpacing.referenceGap!)).toBeLessThan(1);
  await expect(page.locator(".thread-history-slot")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("history-fast-ready-hidden.png") });

  history.useFastResponse(false);
  await positionAtTop(body);
  await stableLayout(body);
  const atNewHead = await historyGeometry(body, "Question 28");
  expect(atNewHead.firstKey).toBe("u28");
  expect(atNewHead.slotBeforeKey).toBeNull();
  expect(atNewHead.slotHeight).toBe(0);
  await expect(header).toBeHidden();
  expect(history.reads).toHaveLength(1);
  await requestOlderWithWheel(body, history, 2);
  await expect(header).toHaveAttribute("data-state", "loading");
  const nextHeld = await expectHeld(body, "Question 28");
  expect(nextHeld.slotBeforeKey).toBe("u28");
  expect(nextHeld.anchorTop - atNewHead.anchorTop).toBeCloseTo(48, 0);
  await completePrepend(history, body, "Question 16", "Question 28", nextHeld.anchorTop);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
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

test("a successful exhausted result reclaims its slot and stays at the real history boundary", async ({ page }) => {
  const history = await installHistory(page, 4);
  const { body } = await openSettledHistory(page);
  const exhausted = page.locator('.thread-history-status[data-state="exhausted"]');
  await expect(exhausted).toHaveCount(0);
  await positionAtTop(body);
  await requestOlderWithWheel(body, history, 1);
  const held = await expectHeld(body, "Question 4");
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 4", held.anchorTop);
  const completionReadingDeltaPx = (await anchorTop(body, "Question 4")) - held.anchorTop;
  expect(Math.abs(completionReadingDeltaPx)).toBeLessThan(1);
  await body.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event("scroll")); });
  await stableLayout(body);
  await expect(exhausted).toBeVisible();
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  const spacing = await historyBoundarySpacing(body, "Question 4", "Question 5");
  console.log("history-exhausted-spacing", JSON.stringify({ ...spacing, readingDeltaPx: completionReadingDeltaPx }));
  expect(Math.abs(spacing.boundaryGap! - spacing.referenceGap!)).toBeLessThan(1);
  expect(spacing.slotCount).toBe(0);
  await page.screenshot({ path: test.info().outputPath("history-exhausted-reclaimed-at-boundary.png") });
  await body.hover();
  await page.mouse.wheel(0, 600);
  await stableLayout(body);
  await expect(exhausted).toHaveCount(0);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
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
  await requestOlderWithWheel(body, history, 3);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeInViewport();
  const held = await expectHeld(body, "Question 38");
  await page.mouse.wheel(0, -80);
  await stableLayout(body);
  const afterRetryPressure = await historyGeometry(body, "Question 38");
  console.log("history-navigation-pressure-settled", JSON.stringify({ held, afterRetryPressure }));
  await expectCoordinates(body, "Question 38", held);
  expect(history.reads).toHaveLength(3);
  history.complete("error");
  await page.getByRole("button", { name: "Loading failed. Retry", exact: true }).click();
  await expect.poll(() => history.reads.length).toBe(4);
  const beforeRetryCompletion = await historyGeometry(body, "Question 38");
  history.complete();
  await expect(body.getByText("Question 26", { exact: true })).toBeAttached();
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
  await expect(page.locator(".thread-history-status")).toHaveCount(0);
  await expect(body.locator(".thread-history-slot")).toHaveCount(0);
  await stableLayout(body);
  const afterRetryCompletion = await historyGeometry(body, "Question 38");
  console.log("history-navigation-retry-completion", JSON.stringify({ beforeRetryCompletion, afterRetryCompletion }));
  await expectAnchorCoordinate(body, "Question 38", held.anchorTop);
  const navigationSpacing = await historyBoundarySpacing(body, "Question 38", "Question 39");
  expect(Math.abs(navigationSpacing.boundaryGap! - navigationSpacing.referenceGap!)).toBeLessThan(1);
  await positionAtTop(body);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
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
  const { body, header, slot } = await openSettledHistory(page);
  await positionAtTop(body);
  await requestOlderWithWheel(body, history, 1);
  const held = await expectHeld(body, "Question 40");
  expect(held.slotBeforeKey).toBe("u40");
  history.complete("error");
  await expect(header).toHaveAttribute("data-state", "error");
  const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
  const blocks = retry.locator(".thread-history-blocks");
  await expect(blocks).toBeInViewport();
  await expect(blocks).toHaveCSS("color", "rgb(185, 28, 28)");
  await expect(blocks.locator("span").first()).not.toHaveCSS("animation-name", "none");
  await expectHeaderInsideSlot(body);
  await expectNoVisibleHistoryText(header);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await stableLayout(body);
  await expectCoordinates(body, "Question 40", held);
  expect(history.reads).toHaveLength(1);

  // This is a fresh pull at the failed boundary, not a ready-button-only path.
  await requestOlderWithWheel(body, history, 2);
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
  await expect(header).toHaveCount(0);
  await expect(blocks).toHaveCount(0);
  await stableLayout(body);
  await expect(slot).toHaveCount(0);
  expect((await historyGeometry(body, "Question 40")).slotBeforeKey).toBeNull();
  await expectAnchorCoordinate(body, "Question 40", held.anchorTop);
  expect(history.reads).toHaveLength(2);
});

test("cross-path unloaded rail jump has visible navigation feedback outside a scrolled-away older slot", async ({ page }) => {
  const history = await installHistory(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const { body, slot } = await openSettledHistory(page, "&navigate=1");
  await positionAtTop(body);
  await requestOlderWithWheel(body, history, 1);
  history.complete();
  await expect(body.getByText("Question 28", { exact: true })).toBeAttached();
  await expect(slot).toHaveCount(0);
  await body.hover();
  await page.mouse.wheel(0, 128);
  // Start the replacement away from the old bottom so setup cannot prefetch newer.
  await positionAtTop(body);
  await stableLayout(body);
  await expect(slot).toHaveCount(0);

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
  const { body, slot } = await openSettledHistory(page, "&navigate=1");
  await positionAtTop(body);
  await stableLayout(body);
  await jumpViaRail(page, 10);
  await expect.poll(() => history.reads.length).toBe(1);
  history.complete();
  await expect(body.getByText("Question 10", { exact: true })).toBeInViewport();
  await stableLayout(body);
  await positionAtTop(body);
  await requestOlderWithWheel(body, history, 2);
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await expect(slot).toHaveCount(0);
  await expect.poll(() => displacement(body)).toBe(0);
  await body.hover();
  await page.mouse.wheel(0, 128);
  await expect(slot).toHaveCount(0);
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
      await openSettledHistory(page, "&navigate=1");
      await positionAtTop(body);
      await requestOlderWithWheel(body, history, initialReads + 1);
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
      await expect(body.locator(".thread-history-slot")).toHaveCount(0);
      await expect(page.locator('.thread-history-status[data-state="loading"]')).toHaveCount(0);
    });
  }
});


test("loading retains its slot and reading anchor at the tolerated top pixel", async ({ page }) => {
  const history = await installHistory(page);
  const { body, header } = await openSettledHistory(page);
  // Home can reach the existing <=1px boundary before its native scroll reaches zero.
  await body.evaluate((node) => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
    node.scrollTop = 1;
    node.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(() => history.reads.length).toBe(1);
  await expect(header).toHaveAttribute("data-state", "loading");
  const held = await expectHeld(body, "Question 40");
  expect(held.scrollTop).toBe(1);
  expect(held.visibleHeight).toBeCloseTo(47, 0);
  expect(held.headerTop).toBeCloseTo(held.frameTop - 1, 0);
  await completePrepend(history, body, "Question 28", "Question 40", held.anchorTop);
});


test("bounded navigation retains three pages and reclaims each completed wheel or keyboard boundary slot", async ({ page }) => {
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
  await requestOlderWithWheel(body, history, 2);
  await expect(header).toHaveAttribute("data-state", "loading");
  const held = await expectHeld(body, "Question 38");
  expect(held.slotBeforeKey).toBe("u38");

  await completePrepend(history, body, "Question 26", "Question 38", held.anchorTop);
  expect((await historyGeometry(body, "Question 38")).slotBeforeKey).toBeNull();
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(24);

  // Reach each prepended page head instead of loading from the old reading slot.
  const atSecondHead = await approachNextHead("Question 26");
  expect(atSecondHead.firstKey).toBe("u26");
  expect(atSecondHead.slotBeforeKey).toBeNull();
  expect(history.reads).toHaveLength(2);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(3);
  await expect(header).toHaveAttribute("data-state", "loading");
  const secondHeld = await expectHeld(body, "Question 26");
  expect(secondHeld.slotBeforeKey).toBe("u26");
  expect(secondHeld.anchorTop - atSecondHead.anchorTop - atSecondHead.scrollTop).toBeCloseTo(48, 0);
  await completePrepend(history, body, "Question 14", "Question 26", secondHeld.anchorTop);
  expect((await historyGeometry(body, "Question 26")).slotBeforeKey).toBeNull();
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(36);

  // Completed feedback is removed and cannot add a fourth cached page.
  await expect(header).toHaveCount(0);
  await stableLayout(body);
  await expect(page.getByText("No earlier messages", { exact: true })).toHaveCount(0);
  await expect(slot).toHaveCount(0);
  await expectAnchorCoordinate(body, "Question 26", secondHeld.anchorTop);
  expect((await historyGeometry(body, "Question 26")).slotBeforeKey).toBeNull();
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26"]);

  const atNewHead = await approachNextHead("Question 14");
  expect(atNewHead.firstKey).toBe("u14");
  expect(atNewHead.slotBeforeKey).toBeNull();
  expect(history.reads).toHaveLength(3);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => history.reads.length).toBe(4);
  await expect(header).toHaveAttribute("data-state", "loading");
  const newHeld = await expectHeld(body, "Question 14");
  expect(newHeld.slotBeforeKey).toBe("u14");
  expect(newHeld.anchorTop - atNewHead.anchorTop - atNewHead.scrollTop).toBeCloseTo(48, 0);
  await completePrepend(history, body, "Question 2", "Question 14", newHeld.anchorTop);
  await expect(slot).toHaveCount(0);
  const completed = await historyGeometry(body, "Question 14");
  expect(completed.slotBeforeKey).toBeNull();
  expect(completed.firstKey).toBe("u2");
  await expect(body.getByText("Question 37", { exact: true })).toBeAttached();
  await expect(body.getByText("Question 38", { exact: true })).toHaveCount(0);
  await expect(body.getByText("Question 49", { exact: true })).toHaveCount(0);
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(36);
  await expect(header).toHaveCount(0);
  await expect(page.getByText("No earlier messages", { exact: true })).toHaveCount(0);
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26", "?limit=24&before=14"]);

  // A real Home key reaches the next boundary and rebinds without a wheel pull.
  const atKeyboardHead = await approachNextHead("Question 2");
  expect(atKeyboardHead.firstKey).toBe("u2");
  expect(atKeyboardHead.slotBeforeKey).toBeNull();
  await body.evaluate((node) => { node.tabIndex = 0; node.focus({ preventScroll: true }); });
  expect(history.reads).toHaveLength(4);
  await page.keyboard.press("Home");
  await expect.poll(() => history.reads.length).toBe(5);
  await expect(header).toHaveAttribute("data-state", "loading");
  const keyboardHeld = await expectHeld(body, "Question 2");
  expect(keyboardHeld.slotBeforeKey).toBe("u2");
  expect(keyboardHeld.anchorTop - atKeyboardHead.anchorTop - atKeyboardHead.scrollTop + keyboardHeld.scrollTop).toBeCloseTo(48, 0);
  history.complete();
  await expect(body.getByText("Question 0", { exact: true })).toBeAttached();
  await stableLayout(body);
  await expectAnchorCoordinate(body, "Question 2", keyboardHeld.anchorTop);
  await body.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event("scroll")); });
  await stableLayout(body);
  await expect(header).toHaveAttribute("data-state", "exhausted");
  await expect(slot).toHaveCount(0);
  const keyboardCompleted = await historyGeometry(body, "Question 2");
  expect(keyboardCompleted.slotBeforeKey).toBeNull();
  expect(keyboardCompleted.firstKey).toBe("u0");
  await expect(body.getByText("Question 25", { exact: true })).toBeAttached();
  await expect(body.getByText("Question 26", { exact: true })).toHaveCount(0);
  await expect(body.locator('[data-thread-display-unit^="u"]')).toHaveCount(26);
  expect(history.reads).toEqual(["?limit=24&after=38", "?limit=24&before=38", "?limit=24&before=26", "?limit=24&before=14", "?limit=24&before=2"]);
});


async function historyBoundarySpacing(body: Locator, boundaryText: string, referenceText: string) {
  return body.evaluate((node, texts) => {
    const units = Array.from(node.querySelectorAll<HTMLElement>("[data-thread-display-unit]"));
    const unitFor = (text: string) => {
      const content = Array.from(node.querySelectorAll<HTMLElement>("[data-user-prompt-id], p"))
        .find((element) => element.textContent?.trim() === text);
      return content?.closest<HTMLElement>("[data-thread-display-unit]") ?? null;
    };
    const gapBefore = (unit: HTMLElement | null) => {
      if (!unit) return null;
      const index = units.indexOf(unit);
      const previous = units[index - 1];
      return previous ? unit.getBoundingClientRect().top - previous.getBoundingClientRect().bottom : null;
    };
    return {
      boundaryGap: gapBefore(unitFor(texts.boundaryText)),
      referenceGap: gapBefore(unitFor(texts.referenceText)),
      slotCount: node.querySelectorAll(".thread-history-slot").length,
    };
  }, { boundaryText, referenceText });
}

async function expectAnchorCoordinate(body: Locator, text: string, expectedTop: number) {
  await expect.poll(async () => Math.abs(await anchorTop(body, text) - expectedTop)).toBeLessThan(1);
}


test("history Blocks use muted loading and destructive error colors in light and dark themes", async ({ browser }) => {
  for (const colorScheme of ["light", "dark"] as const) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme });
    const page = await context.newPage();
    const history = await installHistory(page);
    await page.goto(`http://127.0.0.1:${process.env.NANOBOT_BROWSER_TEST_PORT ?? 4178}/browser/fixture.html?case=history-boundary`);
    if (colorScheme === "dark") await page.locator("html").evaluate((node) => node.classList.add("dark"));
    const body = page.getByTestId("thread-message-region");
    await expect(body).toBeVisible();
    await stableLayout(body);
    await positionAtTop(body);
    await requestOlderWithWheel(body, history, 1);
    const loadingBlocks = page.locator('.thread-history-status[data-state="loading"] .thread-history-blocks');
    const loadingColor = await loadingBlocks.evaluate((node) => getComputedStyle(node).color);
    const mutedColor = await themeColor(loadingBlocks, "--muted-foreground");
    expect(loadingColor).toBe(mutedColor);
    history.complete("error");
    const retry = page.getByRole("button", { name: "Loading failed. Retry", exact: true });
    const errorBlocks = retry.locator(".thread-history-blocks");
    const errorColor = await errorBlocks.evaluate((node) => getComputedStyle(node).color);
    const destructiveColor = await themeColor(errorBlocks, "--destructive");
    expect(errorColor).toBe(destructiveColor);
    expect(errorColor).not.toBe(loadingColor);
    console.log(`history-colors ${colorScheme} loading=${loadingColor} error=${errorColor}`);
    await test.info().attach(`history-colors-${colorScheme}`, {
      body: JSON.stringify({ colorScheme, loadingColor, mutedColor, errorColor, destructiveColor }),
      contentType: "application/json",
    });
    await page.close();
  }
});
