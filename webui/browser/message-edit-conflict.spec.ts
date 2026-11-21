import { expect, test } from "@playwright/test";

// Use the full thread shell: a newer revision alone is not sufficient if the
// conversation the user is about to replace is still stale on screen.
for (const sourceRetained of [true, false]) {
  test(`review a conflicting edit with the source ${sourceRetained ? "retained" : "replaced"}`, async ({ page }) => {
    const chat = "answer-order";
    let changed = false;
    const revisions: string[] = [];
    const turn = (id: string, text: string) => [
      { event: "user_message", chat_id: chat, turn_id: id, turn_seq: 1, starts_turn: true, text },
      { event: "turn_end", chat_id: chat, turn_id: id, turn_seq: 2 },
    ];
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
    await page.route("**/api/sessions/*/webui-thread?*", (route) => route.fulfill({ json: {
      schemaVersion: 3, projection: "events", source_revision: changed ? "new" : "old",
      history_generation: changed && !sourceRetained ? "replacement" : "initial",
      events: [...(!changed || sourceRetained ? turn("original", "Original question") : []),
        ...(changed ? turn("other", "Question from another tab") : [])],
    } }));
    await page.routeWebSocket("**/answer-order-socket", (ws) => ws.onMessage((raw) => {
      const frame = JSON.parse(String(raw));
      if (frame.type === "attach") ws.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      if (frame.action !== "chat.fork") return;
      revisions.push(frame.payload.source.revision);
      ws.send(JSON.stringify({ event: "webui_response", request_id: frame.request_id, ...(changed
        ? { ok: true, result: { accepted: true } } : { ok: false, error: { status: 409, message: "edit_source_changed" } }) }));
      changed = true;
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    const trigger = page.getByRole("button", { name: "Message actions" }).first();
    await trigger.focus();
    await trigger.press("Enter");
    await page.getByRole("button", { name: "Edit message" }).click();
    const editor = page.getByRole("textbox", { name: "Edit message" });
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
    expect(revisions).toEqual(["old"]);
    if (sourceRetained) {
      await resend.click();
      await expect(editor).toHaveCount(0);
      expect(revisions).toEqual(["old", "new"]);
    } else {
      await expect(resend).toBeDisabled();
      await expect(page.getByRole("alert")).toContainText("copy your draft");
    }
  });
}
