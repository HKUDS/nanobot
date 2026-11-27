import { expect, test, type WebSocketRoute } from "@playwright/test";

for (const paged of [true, false]) {
  test(paged ? "resend an edit whose source moved off the latest page" : "keep the draft when another tab replaces the source", async ({ page }) => {
    const chat_id = "answer-order";
    const snapshot = (id: string, text: string, hasEarlier: boolean, media_urls?: { name: string; url: string }[]) => ({
      schemaVersion: 3, projection: "events",
      events: [
        { event: "user_message", chat_id, turn_id: id, input_id: `input-${id}`, turn_seq: 1, starts_turn: true, text, media_urls },
        { event: "turn_end", chat_id, turn_id: id, turn_seq: 2 },
      ],
      page: { has_more_before: hasEarlier, before_cursor: hasEarlier ? "earlier" : null, user_message_offset: hasEarlier ? 1 : 0 },
    });
    let thread = snapshot("original", "", false, [{ name: "notes.pdf", url: "/media/original-notes" }]);
    const edits: unknown[] = [];
    let socket: WebSocketRoute;
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
    await page.route("**/api/sessions/*/webui-thread?*", (route) => route.fulfill({ json: thread }));
    await page.routeWebSocket("**/answer-order-socket", (ws) => ws.onMessage((raw) => {
      const frame = JSON.parse(String(raw));
      if (frame.type === "attach") {
        socket = ws;
        ws.send(JSON.stringify({ event: "attached", chat_id }));
      }
      if (frame.action === "chat.edit") {
        edits.push(frame.payload);
        ws.send(JSON.stringify({ event: "webui_response", request_id: frame.request_id, ok: true, result: { accepted: true } }));
      }
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    const row = page.locator("[data-user-prompt-id]").first();
    await row.hover();
    const edit = row.getByRole("button", { name: "Edit message" });
    await expect(edit).toBeInViewport({ ratio: 1 });
    await edit.click();
    const editor = page.getByRole("textbox", { name: "Edit message" });
    await expect(editor).toBeFocused();
    await expect(editor).toHaveValue("");
    await editor.fill("My edit");
    const attachment = page.getByRole("button", { name: "notes.pdf" });
    await expect(attachment).toBeVisible();

    await expect.poll(() => !!socket).toBe(true);
    thread = snapshot("other", "Question from another tab", paged);
    socket!.send(JSON.stringify({ event: "history_invalidated", chat_id }));
    await expect(page.getByText("Question from another tab", { exact: true })).toBeVisible();
    await expect(editor).toHaveValue("My edit");
    await expect(attachment).toBeVisible();
    if (paged) {
      await page.getByRole("button", { name: "Resend" }).click();
      await expect(editor).toHaveCount(0);
      expect(edits).toEqual([{ chat_id, turn_id: expect.any(String), text: "My edit", source_id: "input-original" }]);
    } else {
      await expect(page.getByRole("alert")).toContainText("copy your draft");
      await expect(page.getByRole("button", { name: "Resend" })).toBeDisabled();
      await editor.press("Control+Enter");
      await expect(editor).toHaveValue("My edit");
      expect(edits).toEqual([]);
    }
  });
}

test("a reconnect that discovers an offline edit keeps the new socket's live reply", async ({ page }) => {
  const chat_id = "answer-order";
  const prompt = (id: string, text: string) => ({ event: "user_message", chat_id, turn_id: id, turn_seq: 1, starts_turn: true, text });
  const delta = (id: string, seq: number, text: string) => ({ event: "delta", chat_id, turn_id: id, turn_seq: seq, stream_id: id, text });
  let socket: WebSocketRoute;
  let attachments = 0;
  let edited = false;
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/sessions/*/webui-thread?*", async (route) => {
    if (edited) await held;
    await route.fulfill({ json: {
      schemaVersion: 3, projection: "events", page: { history_generation: edited ? "edited" : "original", has_more_before: false },
      events: edited ? [prompt("new", "Edited prompt"), delta("new", 2, "Stored ")] : [prompt("old", "Original prompt")],
    } });
  });
  await page.routeWebSocket("**/answer-order-socket", (ws) => ws.onMessage((raw) => {
    if (JSON.parse(String(raw)).type !== "attach") return;
    socket = ws;
    attachments++;
    ws.send(JSON.stringify({ event: "attached", chat_id }));
    if (edited) {
      ws.send(JSON.stringify(delta("new", 2, "Stored ")));
      ws.send(JSON.stringify(delta("new", 3, "live reply")));
    }
  }));
  await page.goto("/browser/fixture.html?case=answer-order&reconnect=1");
  await expect(page.getByText("Original prompt", { exact: true })).toBeVisible();
  await expect.poll(() => attachments).toBe(1);
  socket!.send(JSON.stringify(delta("old", 2, "Retired live reply")));
  await expect(page.getByText("Retired live reply", { exact: true })).toBeVisible();
  edited = true;
  await socket!.close({ code: 1011, reason: "miss edit while offline" });
  await expect.poll(() => attachments).toBe(2);
  await expect(page.getByText("Stored live reply", { exact: true })).toBeVisible();
  release();
  await expect(page.getByText("Edited prompt", { exact: true })).toBeVisible();
  await expect(page.getByText("Stored live reply", { exact: true })).toBeVisible();
  await expect(page.getByText("Original prompt", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Retired live reply", { exact: true })).toHaveCount(0);
});
