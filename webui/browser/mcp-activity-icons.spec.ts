import { execFileSync } from "node:child_process";
import { createServer } from "node:https";
import type { AddressInfo } from "node:net";
import { expect, test, type WebSocketRoute } from "@playwright/test";

const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/2uoAAAAASUVORK5CYII=";
test.use({ ignoreHTTPSErrors: true });

test("direct and restored MCP calls share catalog reads and reuse a cacheable HTTPS icon", async ({ page }, info) => {
  // Only the real HTTP-cache assertion needs OpenSSL. Keep covering the thread
  // with a standard inline PNG on hosts without it. Never route image requests:
  // Playwright HTTP routing would disable Chromium's native HTTP cache.
  let pem: string | undefined;
  try {
    pem = execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost", "-days", "1", "-keyout", "-", "-out", "-"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    info.annotations.push({ type: "coverage", description: "No OpenSSL; tested inline icons, not HTTP cache reuse." });
  }
  const hits: (string | undefined)[] = [];
  const server = pem && createServer({ key: pem, cert: pem }, (req, res) => {
    hits.push(req.headers.referer);
    res.writeHead(200, { "Content-Type": "image/png", "Cache-Control": "public, max-age=3600" });
    res.end(Buffer.from(png, "base64"));
  });
  if (server) await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    const inline = `data:image/png;base64,${png}`;
    const src = server ? `https://127.0.0.1:${(server.address() as AddressInfo).port}/mark.png` : inline;
    const base = { chat_id: "answer-order", turn_id: "mcp-turn" };
    const events = [
      { ...base, event: "user_message", turn_seq: 1, text: "Look up records", starts_turn: true },
      { ...base, event: "message", turn_seq: 2, kind: "tool_hint", text: "mcp_team_docs_find_page({})" },
      { ...base, event: "message", turn_seq: 3, kind: "tool_hint", text: "mcp_reader--local_lookup({})" },
    ];
    await page.addInitScript(({ src, inline, events }) => {
      localStorage.setItem("nanobot.locale", "en");
      localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({ schemaVersion: 1, activityMode: "expanded" }));
      const original = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (!url.pathname.startsWith("/api/")) return original(input, init);
        let body: unknown = {};
        if (url.pathname.endsWith("/mcp-presets")) {
          sessionStorage.setItem("catalogReads", String(Number(sessionStorage.getItem("catalogReads")) + 1));
          body = { installed_count: 2, presets: [{ name: "team", icons: [] }, { name: "team_docs", icons: [{ src }] }],
            plugin_server_icons: { "reader--local": [{ src: inline }] } };
        } else if (url.pathname.endsWith("/webui-thread")) {
          body = { schemaVersion: 3, projection: "events", events: sessionStorage.getItem("restore") ? events : [], has_more: false };
        }
        return Promise.resolve(Response.json(body));
      };
    }, { src, inline, events });
    let socket: WebSocketRoute | undefined;
    await page.routeWebSocket("**/answer-order-socket", route => route.onMessage(raw => {
      const frame = JSON.parse(String(raw));
      if (frame.type === "attach") {
        socket = route;
        route.send(JSON.stringify({ event: "attached", chat_id: frame.chat_id }));
      }
    }));
    await page.goto("/browser/fixture.html?case=answer-order");
    await expect.poll(() => !!socket).toBe(true);
    await expect(page.getByRole("status", { name: "Loading conversation…" })).toHaveCount(0);
    for (const frame of events) socket!.send(JSON.stringify(frame));
    for (const reads of [1, 2]) {
      const mark = page.getByTestId("activity-mcp-logo-team_docs").locator("img").first();
      await expect(mark).toHaveAttribute("src", src);
      await expect.poll(() => mark.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(1);
      await expect(page.getByTestId("activity-mcp-logo-reader--local").locator("img").first()).toHaveAttribute("src", inline);
      expect(await page.evaluate(() => Number(sessionStorage.getItem("catalogReads")))).toBe(reads);
      if (server) expect(hits).toEqual([undefined]); // no referrer, and no second GET after reload
      if (reads === 1) {
        await page.evaluate(() => sessionStorage.setItem("restore", "1"));
        await page.reload();
      }
    }
  } finally {
    if (server) {
      server.closeAllConnections();
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  }
});
