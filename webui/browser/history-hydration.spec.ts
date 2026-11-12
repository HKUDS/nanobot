import { expect, test, type Locator, type Page, type Route, type WebSocketRoute } from "@playwright/test";

import type { InboundEvent, ThreadProjectionEvent, UITurnPhase, WebuiThreadPersistedPayload } from "../src/lib/types";

// Controlled synthetic backend traffic, not a replay of an original user recording.
// Every body assertion goes through the real socket/client/provider/ThreadShell path.
const A = "nan311-a";
const B = "nan311-b";
const TURN = "nan311-active-turn";
const STARTED_AT = Date.parse("2026-10-21T00:00:00Z") / 1000;
const LIVE = "Live answer from the controlled wire";
const EARLY = "Independent closed segment before the live answer.";

function at(turn: string, sequence: number, phase: UITurnPhase, chatId = A) {
  return { chat_id: chatId, turn_id: turn, turn_seq: sequence, turn_phase: phase };
}

function input(turn: string, text: string, chatId = A): ThreadProjectionEvent {
  return { ...at(turn, 0, "user", chatId), event: "user_message", text, starts_turn: true,
    active_turn_id: turn, started_at: STARTED_AT, created_at_ms: STARTED_AT * 1000 };
}

function delta(sequence: number, text: string, streamId = "live-wire"): ThreadProjectionEvent {
  return { ...at(TURN, sequence, "answer"), event: "delta", stream_id: streamId, text };
}

function end(sequence: number, text: string, streamId: string, merge = false): ThreadProjectionEvent {
  return { ...at(TURN, sequence, "answer"), event: "stream_end", stream_id: streamId, text,
    ...(merge ? { resuming: true, merge_next: true } : { resuming: true }) };
}

function closedTurn(turn: string, question: string, answer: string, chatId = A): ThreadProjectionEvent[] {
  return [input(turn, question, chatId),
    { ...at(turn, 1, "answer", chatId), event: "message", text: answer },
    { ...at(turn, 2, "complete", chatId), event: "turn_end" }];
}

function history(events: ThreadProjectionEvent[], options: {
  before?: string; more?: boolean; offset?: number; active?: string; chatId?: string;
} = {}): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3, projection: "events", sessionKey: `websocket:${options.chatId ?? A}`,
    events: events.map((event, index) => ({ ...event,
      projection_id: `synthetic:${event.turn_id}:${event.event}:${event.turn_seq ?? index}`,
    })),
    completed_turn_ids: events.filter((event) => event.event === "turn_end").map((event) => event.turn_id!),
    active_turn_id: options.active ?? null, has_pending_tool_calls: false,
    page: { before_cursor: options.before ?? null, after_cursor: null,
      has_more_before: options.more ?? false, has_more_after: false,
      user_message_offset: options.offset ?? 0, loaded_event_count: events.length,
      truncated_oversized_turn: false },
  };
}

function liveFirstHistory() {
  return history([
    ...closedTurn("nan311-prefix-turn", "Historical prefix question", "Historical prefix answer."),
    input(TURN, "Active synthetic question"),
    end(2, EARLY, "early-wire"),
    { ...at(TURN, 3, "activity"), event: "message", kind: "tool_hint", text: "Synthetic history checkpoint" },
    end(6, LIVE, "live-wire", true),
  ], { before: "nan311-before-2", more: true, offset: 2, active: TURN });
}

interface HistoryRead {
  chatId: string;
  before: string | null;
  after: string | null;
  route: Route;
}

async function installBackend(page: Page) {
  const reads: HistoryRead[] = [];
  const attached: string[] = [];
  const unexpected: unknown[] = [];
  const errors: string[] = [];
  let socket: WebSocketRoute | undefined;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
  await page.route((url) => /^\/api\/sessions\/websocket:nan311-[ab]\/webui-thread$/.test(decodeURIComponent(url.pathname)), (route) => {
    const url = new URL(route.request().url());
    reads.push({ chatId: decodeURIComponent(url.pathname.split("/")[3]!).slice("websocket:".length),
      before: url.searchParams.get("before"), after: url.searchParams.get("after"), route });
    // Deliberately leave this request pending until the test releases this exact page.
  });
  await page.routeWebSocket((url) => url.pathname === "/nan311-fixture-ws", (wire) => {
    socket = wire;
    wire.onMessage((raw) => {
      const frame = JSON.parse(raw.toString()) as { type?: string; chat_id?: string };
      if (frame.type === "attach" && [A, B].includes(frame.chat_id ?? "")) {
        attached.push(frame.chat_id!);
        wire.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      } else unexpected.push(frame);
    });
    wire.send(JSON.stringify({ event: "ready", chat_id: A, client_id: "nan311-synthetic-client" }));
  });
  return {
    reads,
    async read(chatId = A, before: string | null = null, occurrence = 0) {
      const matching = () => reads.filter((read) => read.chatId === chatId && read.before === before && read.after === null);
      await expect.poll(() => matching().length, { message: `Awaiting controlled ${chatId} history before=${before}` }).toBeGreaterThan(occurrence);
      return matching()[occurrence]!;
    },
    async release(read: HistoryRead, payload: WebuiThreadPersistedPayload) {
      await read.route.fulfill({ json: payload });
    },
    async send(event: InboundEvent) {
      expect(socket, "The fixture must establish its genuine WebSocket before input").toBeDefined();
      socket!.send(JSON.stringify(event));
      const turn = "turn_id" in event ? event.turn_id ?? "-" : "-";
      const sequence = "turn_seq" in event ? event.turn_seq ?? "-" : "-";
      // The fixture's non-consuming observer acknowledges client dispatch, not a model installation.
      await expect(page.getByLabel("Synthetic frame receipt")).toHaveText(`${"chat_id" in event ? event.chat_id : "-"}/${turn}/${event.event}/${sequence}`);
    },
    refreshThread() {
      expect(socket, "The fixture must establish its WebSocket before refresh").toBeDefined();
      socket!.send(JSON.stringify({ event: "session_updated", chat_id: A, scope: "thread" }));
    },
    async ready() {
      await expect(page.getByLabel("Synthetic transport status")).toHaveText("open");
      await expect.poll(() => attached.includes(A)).toBe(true);
    },
    healthy() {
      expect(unexpected, "No unimplemented socket mutations should be needed by this fixture").toEqual([]);
      expect(errors, "The real ThreadShell must not throw in the browser").toEqual([]);
    },
  };
}

type Backend = Awaited<ReturnType<typeof installBackend>>;

async function openFixture(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot_debug_ws", "0");
  });
  const backend = await installBackend(page);
  await page.goto("/browser/fixture.html?case=history-hydration");
  await expect(page.getByText("Synthetic NAN-311 history hydration fixture — not a user recording.", { exact: true })).toBeVisible();
  await backend.ready();
  return { backend, body: page.getByTestId("thread-message-region") };
}

async function requestOlder(page: Page, backend: Backend, body: Locator, before: string) {
  await body.hover();
  await page.mouse.wheel(0, -10_000);
  await expect.poll(() => body.evaluate((node) => node.scrollTop)).toBeLessThanOrEqual(1);
  // If the first wheel only reached the head, this second genuine wheel arms the boundary.
  await page.mouse.wheel(0, -120);
  const read = await backend.read(A, before);
  await expect(page.locator('.thread-history-status[data-state="loading"]')).toBeVisible();
  return read;
}

async function expectBefore(body: Locator, first: string, second: string) {
  const text = await body.innerText();
  expect(text.indexOf(first), `${first} must be in the rendered body`).toBeGreaterThanOrEqual(0);
  expect(text.indexOf(second), `${second} must follow ${first}`).toBeGreaterThan(text.indexOf(first));
}

test("idle compaction stays singular across live updates, thread refresh and cold replay", async ({ page }) => {
  const { backend, body } = await openFixture(page);
  const base = closedTurn("idle-completed", "Before idle compression", "Completed answer before idle compression.");
  await backend.release(await backend.read(), history(base));
  await expect(body.getByText("Completed answer before idle compression.", { exact: true })).toBeVisible();
  const compaction = { event: "context_compaction" as const, chat_id: A, compaction_id: "idle-once" };
  await backend.send({ ...compaction, phase: "started" });
  await expect(body.locator('[data-context-compaction="started"]')).toHaveCount(1);
  await backend.send({ ...compaction, phase: "succeeded" });
  await expect(body.locator('[data-context-compaction="succeeded"]')).toHaveCount(1);

  const completed = history([...base, { ...compaction, phase: "succeeded" }]);
  backend.refreshThread();
  await backend.release(await backend.read(A, null, 1), completed);
  await expect(body.locator('[data-context-compaction="succeeded"]')).toHaveCount(1);
  await expectBefore(body, "Completed answer before idle compression.", "Context compacted");
  await page.reload();
  await backend.ready();
  await backend.release(await backend.read(A, null, 2), completed);
  await expect(body.locator('[data-context-compaction="succeeded"]')).toHaveCount(1);
  await expectBefore(body, "Completed answer before idle compression.", "Context compacted");
  backend.healthy();
});

test("pre-request compaction precedes the answer in live output and history replay", async ({ page }) => {
  const { backend, body } = await openFixture(page);
  const base = closedTurn("before-native", "Previous question", "Previous answer.");
  await backend.release(await backend.read(), history(base));
  await expect(body.getByText("Previous answer.", { exact: true })).toBeVisible();
  const question = input(TURN, "Question requiring native compression");
  const compact: ThreadProjectionEvent = { ...at(TURN, 2, "activity"), event: "context_compaction", compaction_id: "native-before-answer", phase: "succeeded" };
  await backend.send(question);
  await backend.send({ event: "context_compaction", chat_id: A, compaction_id: "native-before-answer", phase: "started" });
  await backend.send(compact);
  await backend.send(delta(3, LIVE));
  await backend.send(end(4, LIVE, "live-wire"));
  const complete: ThreadProjectionEvent = { ...at(TURN, 5, "complete"), event: "turn_end" };
  await backend.send(complete);
  await expectBefore(body, "Context compacted", LIVE);
  backend.refreshThread();
  await backend.release(await backend.read(A, null, 1), history([...base, question, compact, end(4, LIVE, "live-wire"), complete]));
  await expect(body.locator('[data-context-compaction="succeeded"]')).toHaveCount(1);
  await expectBefore(body, "Context compacted", LIVE);
  backend.healthy();
});

for (const width of [1440, 390]) {
  test(`synthetic live-first latest admits its prefix without refresh, then prepends two cursor pages (${width}px)`, async ({ page }) => {
    const { backend, body } = await openFixture(page, width);
    const latest = await backend.read();
    await backend.send(input(TURN, "Active synthetic question"));
    await backend.send(delta(5, LIVE));
    await expect(body.getByText(LIVE, { exact: true })).toBeVisible();
    await expect(body.getByText("Historical prefix question", { exact: true })).toHaveCount(0);

    await backend.release(latest, liveFirstHistory());
    await expect(body.getByText("Historical prefix question", { exact: true })).toBeVisible();
    await expect(body.getByText(EARLY, { exact: true })).toBeVisible();
    await expect(body.getByText(LIVE, { exact: true })).toHaveCount(1);
    await expectBefore(body, "Historical prefix question", EARLY);
    await expectBefore(body, EARLY, LIVE);
    expect(backend.reads.filter((read) => read.before === null)).toHaveLength(1);

    const older = await requestOlder(page, backend, body, "nan311-before-2");
    await backend.release(older, history(closedTurn("nan311-older-turn", "Older page question", "Older page answer."),
      { before: "nan311-before-1", more: true, offset: 1 }));
    const olderQuestion = body.getByText("Older page question", { exact: true });
    await expect(olderQuestion).toBeVisible();
    await olderQuestion.scrollIntoViewIfNeeded();
    await expect(olderQuestion).toBeInViewport();
    await expectBefore(body, "Older page question", "Historical prefix question");

    // Reaching the new head may already prefetch this cursor; keep its response held either way.
    const earliest = await requestOlder(page, backend, body, "nan311-before-1");
    await backend.release(earliest, history(closedTurn("nan311-earliest-turn", "Earliest page question", "Earliest page answer.")));
    const firstQuestion = body.getByText("Earliest page question", { exact: true });
    await expect(firstQuestion).toBeVisible();
    await firstQuestion.scrollIntoViewIfNeeded();
    await expect(firstQuestion).toBeInViewport();
    await expectBefore(body, "Earliest page question", "Older page question");

    await backend.send(delta(7, " — fresh continuation"));
    await expect(body.getByText(`${LIVE} — fresh continuation`, { exact: true })).toHaveCount(1);
    await expect(body.getByText(LIVE, { exact: true })).toHaveCount(0);
    expect(backend.reads.map((read) => read.before)).toEqual([null, "nan311-before-2", "nan311-before-1"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    backend.healthy();
  });
}

test("synthetic HTTP-first cumulative text suppresses delayed covered chunks but keeps the fresh continuation", async ({ page }) => {
  const { backend, body } = await openFixture(page);
  const latest = await backend.read();
  const canonical = "Canonical answer";
  await backend.release(latest, history([input(TURN, "HTTP-first question"), end(3, canonical, "resume-wire", true)], { active: TURN }));
  await expect(body.getByText(canonical, { exact: true })).toBeVisible();

  await backend.send(delta(1, "Canonical ", "resume-wire"));
  await backend.send(delta(2, "answer", "resume-wire"));
  await backend.send(delta(4, " plus fresh continuation", "resume-wire"));
  // A normal control frame drains pending text; fresh text is a positive paint checkpoint.
  await backend.send({ event: "goal_status", chat_id: A, turn_id: TURN, status: "running", started_at: STARTED_AT });
  const continued = `${canonical} plus fresh continuation`;
  await expect(body.getByText(continued, { exact: true })).toHaveCount(1);
  // A delayed cumulative end must not reset the now-newer foreground cursor either.
  await backend.send(end(3, canonical, "resume-wire", true));
  await backend.send(delta(5, " after delayed end", "resume-wire"));
  await expect(body.getByText(`${continued} after delayed end`, { exact: true })).toHaveCount(1);
  await expect(body.getByText(canonical, { exact: true })).toHaveCount(0);
  expect(backend.reads).toHaveLength(1);
  backend.healthy();
});

test("synthetic cache return retains unpainted chunks and the absent conversation's buffered wire tail", async ({ page }) => {
  const { backend, body } = await openFixture(page);
  const initial = history([input(TURN, "Cache question"), end(3, "Cache answer", "cache-wire", true)], { active: TURN });
  await backend.release(await backend.read(), initial);
  await expect(body.getByText("Cache answer", { exact: true })).toBeVisible();
  await backend.send(delta(4, " painted", "cache-wire"));
  await expect(body.getByText("Cache answer painted", { exact: true })).toBeVisible();

  // Freeze the actual production paint throttle, not the transport or the model.
  await page.clock.install({ time: new Date("2026-10-21T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-10-21T00:00:10Z"));
  await backend.send(delta(5, " buffered", "cache-wire"));
  await expect(body.getByText("Cache answer painted buffered", { exact: true })).toHaveCount(0);
  // Dispatch the public navigation button without an actionability rAF while paint is frozen.
  await page.getByRole("button", { name: "Conversation B", exact: true }).dispatchEvent("click");
  await expect(page.getByLabel("Synthetic active conversation")).toHaveText(B);
  await backend.release(await backend.read(B), history(closedTurn("nan311-b-turn", "Other conversation question", "Other conversation answer.", B), { chatId: B }));
  await expect(body.getByText("Other conversation answer.", { exact: true })).toBeVisible();
  await expect(body.getByText("Cache answer painted", { exact: true })).toHaveCount(0);
  await backend.send(delta(6, " while-away", "cache-wire"));

  await page.getByRole("button", { name: "Conversation A", exact: true }).dispatchEvent("click");
  await expect(page.getByLabel("Synthetic active conversation")).toHaveText(A);
  const revalidation = await backend.read(A, null, 1);
  // Still-pending HTTP cannot heal a lost cache entry; the received unpainted tail must already be present.
  await expect(body.getByText(/Cache answer painted buffered/)).toHaveCount(1);
  await backend.send(delta(7, " returned", "cache-wire"));
  await page.clock.resume();
  const restored = "Cache answer painted buffered while-away returned";
  await expect(body.getByText(restored, { exact: true })).toHaveCount(1);

  await backend.release(revalidation, history([
    ...closedTurn("nan311-return-prefix", "Return-only historical question", "Return-only historical prefix."),
    ...initial.events,
  ], { active: TURN }));
  await expect(body.getByText("Return-only historical prefix.", { exact: true })).toBeVisible();
  await backend.send(delta(8, " after revalidation", "cache-wire"));
  await expect(body.getByText(`${restored} after revalidation`, { exact: true })).toHaveCount(1);
  await expectBefore(body, "Return-only historical prefix.", `${restored} after revalidation`);
  expect(backend.reads.map((read) => read.chatId)).toEqual([A, B, A]);
  backend.healthy();
});

test("synthetic same-text independent segments in the active turn both appear before the unique live source", async ({ page }) => {
  const { backend, body } = await openFixture(page);
  const latest = await backend.read();
  const repeated = "Repeated independent segment.";
  const foreground = "Unique foreground source";
  await backend.send(input(TURN, "Same-text segments question"));
  await backend.send(delta(8, foreground));
  await expect(body.getByText(foreground, { exact: true })).toBeVisible();
  await backend.release(latest, history([
    input(TURN, "Same-text segments question"),
    end(2, repeated, "independent-wire-a"),
    { ...at(TURN, 3, "activity"), event: "message", kind: "tool_hint", text: "Synthetic boundary A" },
    end(5, repeated, "independent-wire-b"),
    { ...at(TURN, 6, "activity"), event: "message", kind: "tool_hint", text: "Synthetic boundary B" },
    end(9, foreground, "live-wire", true),
  ], { active: TURN }));
  await expect(body.getByText(repeated, { exact: true })).toHaveCount(2);
  for (const segment of await body.getByText(repeated, { exact: true }).all()) await expect(segment).toBeVisible();
  await expectBefore(body, repeated, foreground);
  await backend.send(delta(10, " continues"));
  await expect(body.getByText(`${foreground} continues`, { exact: true })).toHaveCount(1);
  await expect(body.getByText(repeated, { exact: true })).toHaveCount(2);
  expect(backend.reads).toHaveLength(1);
  backend.healthy();
});
