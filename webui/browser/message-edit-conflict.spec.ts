import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

async function editFirstMessage(page: Page) {
  await page.getByRole("button", { name: "Message actions" }).first().press("Enter");
  await page.getByRole("button", { name: "Edit message" }).click();
  return page.getByRole("textbox", { name: "Edit message" });
}

for (const source of ["on an earlier page", "replaced"]) {
  test(`review a conflicting edit with the source ${source}`, async ({ page }) => {
    const chat = "answer-order";
    let changed = false;
    const edits: unknown[] = [];
    const turn = (id: string, text: string) => [
      { event: "user_message", chat_id: chat, turn_id: id, input_id: `input-${id}`, turn_seq: 1, starts_turn: true, text },
      { event: "turn_end", chat_id: chat, turn_id: id, turn_seq: 2 },
    ];
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
    await page.route("**/api/sessions/*/webui-thread?*", (route) => {
      const earlier = new URL(route.request().url()).searchParams.has("before");
      const hasMore = changed && source === "on an earlier page" && !earlier;
      return route.fulfill({ json: {
        schemaVersion: 3, projection: "events", source_revision: changed ? "new" : "old",
        history_generation: changed ? "replacement" : "initial",
        page: { has_more_before: hasMore, before_cursor: hasMore ? "earlier" : null, user_message_offset: hasMore ? 1 : 0 },
        events: !changed || earlier ? turn("original", "Original question") : turn("other", "Question from another tab"),
      } });
    });
    await page.routeWebSocket("**/answer-order-socket", (ws) => ws.onMessage((raw) => {
      const frame = JSON.parse(String(raw));
      if (frame.type === "attach") ws.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      if (frame.action !== "chat.fork") return;
      edits.push(frame.payload);
      ws.send(JSON.stringify({ event: "webui_response", request_id: frame.request_id, ...(frame.payload.source.revision === "new"
        ? { ok: true, result: { accepted: true } } : { ok: false, error: { status: 409, message: "edit_source_changed" } }) }));
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    await expect(page.getByText("Original question", { exact: true })).toBeVisible();
    // Another tab commits before this tab even opens its first editor.
    changed = true;
    const editor = await editFirstMessage(page);
    await editor.fill("My draft");
    const resend = page.getByRole("button", { name: "Resend" });
    await resend.click();
    const review = page.getByRole("button", { name: "Review latest conversation" });
    await expect(review).toBeEnabled();
    await editor.fill("Still my draft");
    await editor.press("Control+Enter");
    await expect(page.getByRole("alert")).toContainText("conversation changed");
    await review.click();
    await expect(page.getByText("Question from another tab", { exact: true })).toBeVisible();
    await expect(editor).toHaveValue("Still my draft");
    const staleEdit = { text: "My draft", source: { revision: "old", id: "input-original" } };
    expect(edits).toMatchObject([staleEdit]);
    if (source === "on an earlier page") {
      await page.getByRole("button", { name: "Load earlier messages" }).click();
      await expect(resend).toBeEnabled();
      await editor.press("Control+Enter");
      await expect(editor).toHaveCount(0);
      expect(edits).toMatchObject([staleEdit, {
        mode: "replace", chat_id: chat, text: "Still my draft", source: { revision: "new", id: "input-original" },
      }]);
    } else {
      await expect(resend).toBeDisabled();
      await expect(page.getByRole("alert")).toContainText("copy your draft");
    }
  });
}

test("reviews live first input against visible history before resending", async ({ page }) => {
  const chat_id = "answer-order";
  const turn_id = "live-first";
  const user = { event: "user_message", chat_id, turn_id, turn_seq: 1, starts_turn: true, text: "Live first input" };
  const end = { event: "turn_end", chat_id, turn_id, turn_seq: 3 };
  let persisted = false;
  let socket: WebSocketRoute;
  const sources: unknown[] = [];
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/sessions/*/webui-thread?*", (route) => persisted ? route.fulfill({ json: {
    schemaVersion: 3, projection: "events", source_revision: "persisted", events: [user,
      { event: "message", chat_id, turn_id, turn_seq: 2, text: "Persisted reply" }, end],
  } }) : route.fulfill({ status: 404, json: {} }));
  await page.routeWebSocket("**/answer-order-socket", (route) => route.onMessage((raw) => {
    const frame = JSON.parse(String(raw));
    if (frame.type === "attach") {
      route.send(JSON.stringify({ event: "attached", chat_id }));
      socket = route;
    }
    if (frame.action === "chat.fork") {
      sources.push(frame.payload.source);
      route.send(JSON.stringify({ event: "webui_response", request_id: frame.request_id, ok: true, result: { accepted: true } }));
    }
  }));
  await page.goto("/browser/fixture.html?case=answer-order");
  await expect.poll(() => !!socket).toBe(true);
  socket!.send(JSON.stringify(user));
  socket!.send(JSON.stringify(end));
  const editor = await editFirstMessage(page);
  await editor.fill("Edited first input");
  await editor.press("Control+Enter");
  expect(sources).toEqual([]);
  persisted = true;
  await page.getByRole("button", { name: "Review latest conversation" }).click();
  await expect(page.getByText("Persisted reply", { exact: true })).toBeVisible();
  await expect(editor).toHaveValue("Edited first input");
  await page.getByRole("button", { name: "Resend" }).click();
  await expect(editor).toHaveCount(0);
  expect(sources).toEqual([{ revision: "persisted", id: "user:live-first" }]);
});
