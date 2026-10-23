import { expect, test, type WebSocketRoute } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`a delivered pairing request reaches the real app through the existing socket at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.clock.install();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let socket: WebSocketRoute | undefined;
    let reads = 0;
    let requests: Record<string, unknown>[] = [];
    await page.route("**/webui/bootstrap*", route => route.fulfill({ json: {
      token: "fixture-token", api_token: "fixture-api-token", ws_path: "/state-events-fixture", expires_in: 300,
      terminal: { webui: { capabilities: ["webui.core.v1"] } },
    } }));
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/settings/pairing") {
        reads += 1;
        return route.fulfill({ json: { requests } });
      }
      if (path === "/api/sessions") return route.fulfill({ json: { sessions: [] } });
      if (path === "/api/skills") return route.fulfill({ json: { skills: [] } });
      if (path === "/api/webui/sidebar-state") return route.fulfill({ json: {} });
      if (path === "/api/remote-instances") return route.fulfill({ status: 403, json: {} });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.routeWebSocket("**/state-events-fixture*", ws => {
      socket = ws;
      ws.send(JSON.stringify({ event: "ready", chat_id: "fixture-chat" }));
    });
    await page.goto("/");
    // Entry loads a snapshot; the first socket open closes the pre-connection gap.
    await expect.poll(() => reads).toBe(2);
    await expect(page.getByRole("textbox", { name: "Message input" })).toBeVisible();
    await page.clock.fastForward(60_000);
    expect(reads).toBe(2);
    requests = [{ code: "ABCD-EFGH", channel: "feishu", sender_id: "fixture-user", delivery_status: "sent" }];
    expect(socket).toBeDefined();
    socket!.send(JSON.stringify({ event: "webui_state_changed", resources: ["pairing"] }));
    const popup = page.getByRole("dialog", { name: "Pair account" });
    await expect(popup).toBeVisible();
    await expect(popup.getByRole("textbox", { name: "Pairing code" })).toBeEnabled();
    await expect.poll(() => reads).toBe(3);
    await popup.getByRole("button", { name: "Close", exact: true }).click();
    await expect(popup).toBeHidden();
    await page.clock.fastForward(30_000);
    await expect(popup).toBeVisible();
    expect(reads).toBe(3);
    expect(errors).toEqual([]);
  });
}
