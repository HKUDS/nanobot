import { expect, test, type WebSocketRoute } from "@playwright/test";

for (const paged of [true, false]) {
  test(paged ? "resend an edit whose source moved off the latest page" : "keep the draft when another tab replaces the source", async ({ page }) => {
    const chat_id = "answer-order";
    const snapshot = (id: string, text: string, hasEarlier: boolean) => ({
      schemaVersion: 3, projection: "events", history_generation: id,
      events: [
        { event: "user_message", chat_id, turn_id: id, input_id: `input-${id}`, turn_seq: 1, starts_turn: true, text },
        { event: "turn_end", chat_id, turn_id: id, turn_seq: 2 },
      ],
      page: { has_more_before: hasEarlier, before_cursor: hasEarlier ? "earlier" : null, user_message_offset: hasEarlier ? 1 : 0 },
    });
    let thread = snapshot("original", "Original question", false);
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
      if (frame.action === "chat.fork") {
        edits.push(frame.payload);
        ws.send(JSON.stringify({ event: "webui_response", request_id: frame.request_id, ok: true, result: { accepted: true } }));
      }
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    await page.getByRole("button", { name: "Message actions" }).first().press("Enter");
    await page.getByRole("button", { name: "Edit message" }).click();
    const editor = page.getByRole("textbox", { name: "Edit message" });
    await editor.fill("My edit");

    await expect.poll(() => !!socket).toBe(true);
    thread = snapshot("other", "Question from another tab", paged);
    socket!.send(JSON.stringify({ event: "history_replaced", chat_id, previous_generation: "original", thread }));
    await expect(page.getByText("Question from another tab", { exact: true })).toBeVisible();
    await expect(editor).toHaveValue("My edit");
    if (paged) {
      await page.getByRole("button", { name: "Resend" }).click();
      await expect(editor).toHaveCount(0);
      expect(edits).toEqual([{ mode: "replace", chat_id, turn_id: expect.any(String), text: "My edit", source_id: "input-original" }]);
    } else {
      await expect(page.getByRole("alert")).toContainText("copy your draft");
      await expect(page.getByRole("button", { name: "Resend" })).toBeDisabled();
      await editor.press("Control+Enter");
      await expect(editor).toHaveValue("My edit");
      expect(edits).toEqual([]);
    }
  });
}
