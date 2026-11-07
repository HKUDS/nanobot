import { expect, test, type WebSocketRoute } from "@playwright/test";

for (const width of [1440, 390]) {
  test(`pairing appears on the real client's event 1s after an empty read at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.clock.install();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const sockets: WebSocketRoute[] = [];
    let reads = 0;
    let requests: Record<string, unknown>[] = [];
    await page.route("**/webui/bootstrap*", route => route.fulfill({ json: {
      token: "fixture-token", api_token: "fixture-api-token", ws_path: "/pairing-events-fixture", expires_in: 300,
      terminal: { webui: { capabilities: ["webui.core.v1"] } },
    } }));
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/settings/pairing") {
        expect(route.request().headers().authorization).toBe("Bearer fixture-api-token");
        reads += 1;
        return route.fulfill({ json: { requests } });
      }
      if (path === "/api/sessions") return route.fulfill({ json: { sessions: [] } });
      if (path === "/api/skills") return route.fulfill({ json: { skills: [] } });
      if (path === "/api/webui/sidebar-state") return route.fulfill({ json: {} });
      if (path === "/api/remote-instances") return route.fulfill({ status: 403, json: {} });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.routeWebSocket("**/pairing-events-fixture*", ws => {
      expect(new URL(ws.url()).searchParams.get("token")).toBe("fixture-token");
      sockets.push(ws);
    });
    await page.goto("/");
    const composer = page.getByRole("textbox", { name: "Message input" });
    await expect(composer).toBeVisible();
    await expect.poll(() => reads).toBe(1);
    await expect.poll(() => sockets.length).toBe(1);
    // The first ready snapshot closes the pre-connection gap without replacing polling.
    sockets[0].send(JSON.stringify({ event: "ready", chat_id: "fixture-chat" }));
    await expect.poll(() => reads).toBe(2);
    await composer.fill("Keep this draft during pairing and reconnect");
    await page.clock.fastForward(1_000);
    expect(reads).toBe(2);
    requests = [{ code: "ABCD-EFGH", channel: "feishu", sender_id: "fixture-user", delivery_status: "sent" }];
    expect(sockets).toHaveLength(1);
    sockets[0].send(JSON.stringify({ event: "pairing_changed" }));
    const popup = page.getByRole("dialog", { name: "Pair account" });
    await expect(popup).toBeVisible();
    await expect(popup.getByRole("textbox", { name: "Pairing code" })).toBeEnabled();
    await expect.poll(() => reads).toBe(3);
    requests = [];
    sockets[0].close({ code: 1012, reason: "pairing fixture reconnect" });
    await page.clock.fastForward(1_000);
    await expect.poll(() => sockets.length).toBe(2);
    sockets[1].send(JSON.stringify({ event: "ready", chat_id: "fixture-chat" }));
    await expect.poll(() => reads).toBe(4);
    await expect(popup).toBeHidden();
    // Changes from another process and expiry need no same-gateway notification.
    requests = [{ code: "IJKL-MNOP", channel: "feishu", sender_id: "fixture-user", delivery_status: "sent" }];
    await page.clock.runFor(15_000);
    await expect(popup).toBeVisible();
    await expect.poll(() => reads).toBe(5);
    requests = [];
    await page.clock.runFor(5_000);
    await expect(popup).toBeHidden();
    await expect.poll(() => reads).toBe(6);
    await expect(composer).toHaveValue("Keep this draft during pairing and reconnect");
    expect(errors).toEqual([]);
  });
}
