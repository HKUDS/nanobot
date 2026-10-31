import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import type { InboundEvent, ThreadProjectionEvent } from "../src/lib/types";

const chatId = "answer-order";
const turnId = "answer-order-turn";
const source = { provider: "fixture", model: "fixture", preset: "fixture" };
const base = { chat_id: chatId, turn_id: turnId };

async function openThread(page: Page, events: ThreadProjectionEvent[] = [], locale = "en") {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript((language) => { localStorage.setItem("nanobot.locale", language); }, locale);
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
  await page.route("**/api/sessions/*/webui-thread?*", (route) => {
    const requestedPath = decodeURIComponent(new URL(route.request().url()).pathname);
    const history = requestedPath.includes(`/sessions/websocket:${chatId}/`) ? events : [];
    return route.fulfill({ json: {
      schemaVersion: 3, projection: "events", events: history, has_more: false,
      has_pending_tool_calls: history.length > 0,
    } });
  });
  let socket!: WebSocketRoute;
  const attached = new Set<string>();
  await page.routeWebSocket("**/answer-order-socket", (route) => {
    socket = route;
    route.onMessage((raw) => {
      const frame = JSON.parse(String(raw));
      if (frame.type === "attach") {
        attached.add(frame.chat_id);
        route.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      }
    });
  });
  await page.goto("/browser/fixture.html?case=answer-order");
  await expect.poll(() => attached.has(chatId)).toBe(true);
  await expect(page.getByRole("status", { name: "Loading conversation…" })).toHaveCount(0);
  return { emit: (...frames: InboundEvent[]) => frames.forEach((frame) => socket.send(JSON.stringify(frame))), errors };
}

async function expectAnswerOrder(page: Page) {
  await expect(page.getByText("Earlier answer", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Later answer", { exact: true })).toHaveCount(1);
  const texts = await page.locator("[data-thread-display-unit]").allTextContents();
  expect(texts.findIndex((text) => text.includes("Earlier answer")))
    .toBeLessThan(texts.findIndex((text) => text.includes("Later answer")));
}

for (const scenario of [
  { locale: "en", width: 1440, waiting: /Connection failed Retrying in [1-9][0-9]*s/, retrying: "Connection failed Retrying" },
  { locale: "zh-CN", width: 390, waiting: /连接失败 [1-9][0-9]* 秒后重试/, retrying: "连接失败 正在重试" },
]) {
  test(`shows retry progress in the live thread at ${scenario.width}px (${scenario.locale})`, async ({ page }, info) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    await page.clock.install();
    const { emit, errors } = await openThread(page, [], scenario.locale);
    emit({ event: "user_message", ...base, text: "Retry fixture", starts_turn: true, active_turn_id: turnId });
    await expect(page.getByText("Retry fixture", { exact: true })).toBeVisible();
    emit(
      { event: "goal_status", ...base, status: "running", started_at: Date.now() / 1000 },
      { event: "retry_status", ...base, state: "waiting", attempt: 1, max_attempts: 4, error_kind: "connection", retry_after_s: 30 },
    );
    await expect(page.getByRole("status", { name: scenario.waiting })).toBeVisible();
    await page.screenshot({ path: info.outputPath("retry-waiting.png") });
    await page.clock.fastForward(30_000);
    await expect(page.getByRole("status", { name: scenario.retrying, exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath("retry-status.png") });
    emit({ event: "retry_status", ...base, state: "recovered", attempt: 2, max_attempts: 4, error_kind: "connection" });
    await expect(page.getByRole("status", { name: scenario.retrying, exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test.describe("answer order", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  for (const path of ["callback", "cached return"] as const) {
    test(`keeps closed answer order through ${path} and textless streams`, async ({ page }, info) => {
      const { emit, errors } = await openThread(page);
      emit(
        { event: "goal_status", ...base, status: "running", started_at: 100 },
        { event: "delta", ...base, stream_id: "first", turn_seq: 1, text: "Earlier answer" },
        { event: "stream_end", ...base, stream_id: "first", turn_seq: 2, resuming: true, response_sources: [source] },
        { event: "message", ...base, turn_seq: 3, kind: "tool_hint", text: "read_file(earlier)" },
        { event: "delta", ...base, stream_id: "second", turn_seq: 4, text: "Later answer" },
        { event: "stream_end", ...base, stream_id: "second", turn_seq: 5, resuming: true, response_sources: [source] },
        { event: "message", ...base, turn_seq: 6, kind: "tool_hint", text: "read_file(later)" },
      );
      await expectAnswerOrder(page);
      if (path === "callback") {
        await page.getByRole("button", { name: "Rebuild subscription" }).click();
      } else {
        await page.getByRole("button", { name: "Switch topic" }).click();
        await expect(page.getByText("Earlier answer", { exact: true })).toHaveCount(0);
      }
      emit(
        { event: "stream_end", ...base, stream_id: "empty-one", turn_seq: 7, resuming: true, response_sources: [source] },
        { event: "stream_end", ...base, stream_id: "empty-two", turn_seq: 8, resuming: true, response_sources: [source] },
      );
      if (path === "cached return") await page.getByRole("button", { name: "Switch topic" }).click();
      // The late final snapshot belongs to the first row, not the latest row.
      emit({ event: "stream_end", ...base, stream_id: "first", turn_seq: 9, text: "Earlier answer", response_sources: [] });
      await expectAnswerOrder(page);
      await expect(page.getByRole("button", { name: "Stop response" })).toBeVisible();
      await page.screenshot({ path: info.outputPath("answer-order.png") });
      emit({ event: "turn_end", ...base, turn_seq: 10 });
      await expect(page.getByRole("button", { name: "Stop response" })).toHaveCount(0);
      emit({ event: "delta", ...base, stream_id: "late", turn_seq: 11, text: "Obsolete answer" });
      // Ordered WebSocket processing: a subsequent new-turn frame is the barrier.
      emit({ event: "message", chat_id: chatId, turn_id: "new-turn", text: "Next turn" });
      await expect(page.getByText("Next turn", { exact: true })).toBeVisible();
      await expect(page.getByText("Obsolete answer", { exact: true })).toHaveCount(0);
      await expectAnswerOrder(page);
      expect(errors).toEqual([]);
    });
  }

  test("keeps hosted-tool answer segments after a cached return", async ({ page }) => {
    const { emit, errors } = await openThread(page);
    emit(
      { event: "goal_status", ...base, status: "running", started_at: 100 },
      { event: "delta", ...base, stream_id: "hosted", turn_seq: 1, text: "First " },
      { event: "stream_end", ...base, stream_id: "hosted", turn_seq: 2, resuming: true },
      { event: "message", ...base, turn_seq: 3, kind: "tool_hint", text: "web_search(query)" },
      { event: "delta", ...base, stream_id: "after-tool", turn_seq: 4, text: "second" },
      { event: "stream_end", ...base, stream_id: "after-tool", turn_seq: 5, text: "second", resuming: true, merge_next: true },
    );
    await expect(page.getByText("First", { exact: true })).toHaveCount(1);
    await expect(page.getByText("second", { exact: true })).toHaveCount(1);
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(page.getByText("second", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(page.getByText("second", { exact: true })).toHaveCount(1);
    emit(
      { event: "delta", ...base, stream_id: "after-tool", turn_seq: 6, text: " last" },
      { event: "stream_end", ...base, stream_id: "after-tool", turn_seq: 7, text: "second last", response_sources: [source] },
    );
    await expect(page.getByText("First", { exact: true })).toHaveCount(1);
    await expect(page.getByText("second last", { exact: true })).toHaveCount(1);
    const texts = await page.locator("[data-thread-display-unit]").allTextContents();
    expect(texts.findIndex((text) => text.includes("First"))).toBeLessThan(texts.findIndex((text) => text.includes("second last")));
    expect(errors).toEqual([]);
  });

  for (const width of [1440, 390]) {
    test(`replays legacy cumulative answers on both sides of a hosted tool at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      const { errors } = await openThread(page, [
        { event: "stream_end", ...base, stream_id: "legacy", turn_seq: 2, text: "First ", resuming: true, merge_next: true },
        { event: "message", ...base, turn_seq: 3, kind: "tool_hint", text: "web_search(query)" },
        { event: "stream_end", ...base, stream_id: "legacy", turn_seq: 5, text: "First last" },
        { event: "turn_end", ...base, turn_seq: 6 },
      ]);
      const first = page.getByText("First", { exact: true });
      const last = page.getByText("last", { exact: true });
      await expect(first).toHaveCount(1);
      await expect(last).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Stop response" })).toHaveCount(0);
      const lastBlock = last.locator("xpath=ancestor::*[@data-thread-display-unit]");
      await lastBlock.hover();
      await lastBlock.getByRole("button", { name: "Message actions" }).click();
      await page.locator("[data-message-block-activity-action]").click();
      const tool = page.getByText(/Searched the web/).first();
      await expect(tool).toBeVisible();
      const [firstNode, lastNode] = await Promise.all([first.elementHandle(), last.elementHandle()]);
      expect(await tool.evaluate((node, [before, after]) => (
        !!(before.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)
        && !!(node.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING)
      ), [firstNode!, lastNode!])).toBe(true);
      expect(errors).toEqual([]);
    });
  }

  test("keeps a rewritten image intact before a hosted tool", async ({ page }, info) => {
    const { emit, errors } = await openThread(page);
    await page.route("**/api/media/**", (route) => route.fulfill({ contentType: "image/png", body: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5hUAAAAASUVORK5CYII=", "base64",
    ) }));
    emit(
      { event: "delta", ...base, stream_id: "image", turn_seq: 1, text: "![plot](plot.png)" },
      { event: "stream_end", ...base, stream_id: "image", turn_seq: 2, text: "![plot](/api/media/signature/plot.png)", resuming: true },
      { event: "message", ...base, turn_seq: 3, kind: "tool_hint", text: "web_search(query)" },
      { event: "delta", ...base, stream_id: "after-tool", turn_seq: 4, text: "After tool." },
      { event: "stream_end", ...base, stream_id: "after-tool", turn_seq: 5 },
    );
    const image = page.getByRole("img", { name: "plot", exact: true });
    await expect(image).toHaveCount(1);
    await expect(image).toHaveAttribute("src", /\/api\/media\/signature\/plot.png/);
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBe(1);
    await expect(page.getByText("After tool.", { exact: true })).toHaveCount(1);
    const units = page.locator("[data-thread-display-unit]");
    const imageIndex = await units.evaluateAll((elements) => elements.findIndex((element) => element.querySelector('img[alt="plot"]')));
    const texts = await units.allTextContents();
    const toolIndex = texts.findIndex((text) => text.includes("Searching the web"));
    expect(imageIndex).toBeLessThan(toolIndex);
    expect(toolIndex).toBeLessThan(texts.findIndex((text) => text.includes("After tool.")));
    await page.screenshot({ path: info.outputPath("hosted-tool-image.png") });
    emit({ event: "turn_end", ...base, turn_seq: 6 });
    await expect(page.getByRole("button", { name: "Stop response" })).toHaveCount(0);
    await expect(image).toHaveCount(1);
    await expect(page.getByText("After tool.", { exact: true })).toHaveCount(1);
    expect(errors).toEqual([]);
  });

  test("resumes merge_next with cumulative HTTP snapshots", async ({ page }) => {
    const events: ThreadProjectionEvent[] = [
      { event: "stream_end", ...base, stream_id: "answer", turn_seq: 2, text: "First ", resuming: true, merge_next: true, projection_id: "http-first" },
      { event: "reasoning_end", ...base, stream_id: "answer", turn_seq: 3, text: "More reasoning", projection_id: "http-reasoning" },
      { event: "stream_end", ...base, stream_id: "answer", turn_seq: 5, text: "First last", resuming: true, merge_next: true, projection_id: "http-last" },
    ];
    const { emit, errors } = await openThread(page, events);
    await expect(page.getByText("First last", { exact: true })).toHaveCount(1);
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(page.getByText("First last", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(page.getByText("First last", { exact: true })).toHaveCount(1);
    emit(
      { event: "goal_status", ...base, status: "running", started_at: 100 },
      { event: "delta", ...base, stream_id: "answer", turn_seq: 6, text: " continued" },
      { event: "stream_end", ...base, stream_id: "answer", turn_seq: 7, text: "First last continued", response_sources: [source] },
    );
    await expect(page.getByText("First last continued", { exact: true })).toHaveCount(1);
    await expect(page.getByText("First last", { exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
