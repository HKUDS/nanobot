import { expect, test, type Page } from "@playwright/test";

// Independent wire fixture: ready pins the epoch; transcript events never grant execution authority.
async function host(page: Page, authority = true) {
  let revision = 0;
  let wire!: { send(data: string): void };
  const frames: Array<{
    type?: string; action?: string; content?: string; request_id?: string; turn_id?: string;
    payload?: { run_ids?: string[] };
  }> = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith("/webui-thread")
      ? { schemaVersion: 3, projection: "events", events: [], has_pending_tool_calls: false }
      : path.endsWith("/commands") ? { commands: [] } : {} });
  });
  const snapshot = (runs: unknown[] = []) => ({
    instance_id: "protocol-host", revision: ++revision, runs,
  });
  const emit = (event: unknown) => wire.send(JSON.stringify(event));
  await page.routeWebSocket("**/answer-order-socket", (socket) => {
    wire = socket;
    socket.onMessage((raw) => {
      const frame = JSON.parse(String(raw));
      frames.push(frame);
      if (frame.type === "attach") emit({ event: "attached", chat_id: frame.chat_id,
        ...(authority ? { run_state: snapshot() } : {}) });
      if (authority && frame.type === "watch_runs") for (const chatId of frame.chat_ids) {
        emit({ event: "run_state", chat_id: chatId, run_state: snapshot() });
      }
    });
    emit({ event: "ready", chat_id: "answer-order", client_id: "protocol-client",
      ...(authority ? { run_state_instance_id: "protocol-host" } : {}) });
  });
  await page.goto("/browser/fixture.html?case=answer-order");
  await expect(page.getByRole("textbox", { name: "Message input", exact: true })).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading conversation…" })).toHaveCount(0);
  return { emit, frames, errors, state: (runs: unknown[]) =>
    emit({ event: "run_state", chat_id: "answer-order", run_state: snapshot(runs) }) };
}

const base = { chat_id: "answer-order", turn_id: "protocol-turn" };
const owner = { run_id: "actual-execution-owner", turn_id: base.turn_id, phase: "running", started_at: 100 };

test("Stop targets the authoritative owner and waits beyond ACK and transcript completion", async ({ page }) => {
  const { emit, frames, errors, state } = await host(page);
  emit({ event: "user_message", ...base, turn_seq: 1, text: "Received input", starts_turn: true });
  await expect(page.getByText("Received input", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop response", exact: true })).toHaveCount(0);
  state([owner]);
  await page.getByRole("button", { name: "Stop response", exact: true }).click();
  await expect.poll(() => frames.filter((frame) => frame.action === "runs.stop").length).toBe(1);
  const stop = frames.find((frame) => frame.action === "runs.stop")!;
  expect(stop.payload?.run_ids).toEqual([owner.run_id]);
  emit({ event: "webui_response", request_id: stop.request_id, ok: true, result: {} });
  state([{ ...owner, phase: "stopping" }]);
  const pending = page.getByRole("button", { name: "Stop requested. Waiting for the task to exit…", exact: true });
  await expect(pending).toBeDisabled();
  emit({ event: "stream_end", ...base, turn_seq: 2, stream_id: "final", text: "Final text" });
  emit({ event: "turn_end", ...base, turn_seq: 3 });
  await expect(page.getByText("Final text", { exact: true })).toBeVisible();
  await expect(pending).toBeDisabled();
  state([]);
  await expect(pending).toHaveCount(0);
  await expect(page.locator("[data-run-status]")).toHaveCount(0);
  await expect(page.getByText("Final text", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("queued input waits for both execution exit and transcript completion, then sends once", async ({ page }) => {
  const { emit, frames, errors, state } = await host(page);
  emit({ event: "user_message", ...base, turn_seq: 1, text: "Original request", starts_turn: true });
  state([owner]);
  await expect(page.getByRole("button", { name: "Stop response", exact: true })).toBeVisible();
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("Queued followup");
  await input.press("Enter");
  await expect(page.getByRole("group", { name: "Waiting to send" })).toContainText("Queued followup");
  state([]);
  await expect(page.locator("[data-run-status=resultUnknown]")).toBeVisible();
  expect(frames.filter((frame) => frame.type === "message")).toHaveLength(0);
  emit({ event: "stream_end", ...base, turn_seq: 2, stream_id: "final", text: "Original final" });
  emit({ event: "turn_end", ...base, turn_seq: 3 });
  await expect.poll(() => frames.filter((frame) => frame.type === "message").length).toBe(1);
  const sent = frames.find((frame) => frame.type === "message")!;
  expect(sent.content).toBe("Queued followup");
  await expect(page.getByRole("group", { name: "Waiting to send" })).toHaveCount(0);
  state([]);
  await expect(page.locator("[data-message-delivery=sending], [data-run-status=sending]").first()).toBeVisible();
  expect(frames.filter((frame) => frame.type === "message")).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("a host without runs.v1 can admit appended input without duplicating its legacy answer", async ({ page }) => {
  const { emit, frames, errors } = await host(page, false);
  emit({ event: "user_message", ...base, text: "Original request", starts_turn: true });
  emit({ event: "delta", ...base, turn_seq: 1, text: "Initial findings" });
  await expect(page.getByText("Initial findings", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Stop response", exact: true })).toHaveCount(0);
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("Focus on primary sources");
  await input.press("Enter");
  await expect.poll(() => frames.filter((frame) => frame.type === "message").length).toBe(1);
  const sent = frames.find((frame) => frame.type === "message")!;
  emit({ event: "user_message", chat_id: base.chat_id, turn_id: sent.turn_id,
    text: "Focus on primary sources", active_turn_id: base.turn_id, starts_turn: false });
  emit({ event: "stream_end", ...base, turn_seq: 2, text: "Initial findings", resuming: true });
  emit({ event: "turn_end", ...base, turn_seq: 3 });
  await expect(page.getByText("Focus on primary sources", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Initial findings", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Stop response", exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
