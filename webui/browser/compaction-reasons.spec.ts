import { readFileSync } from "node:fs";
import { expect, test, type WebSocketRoute } from "@playwright/test";
import { supportedLocales } from "../src/i18n/config";
import type { ThreadProjectionEvent } from "../src/lib/types";

const reasons = ["idle", "context_pressure", "manual", "provider_native"] as const;
const phases = ["started", "succeeded", "failed", "cancelled"] as const;

// Synthetic HTTP history and WebSocket delivery through the production client,
// projection, cache, and thread. No model/provider execution is involved.
for (const { code } of supportedLocales) {
  test(`compaction reasons survive live updates and session reentry in ${code}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const messages: typeof import("../src/i18n/locales/en/common.json") = JSON.parse(
      readFileSync(new URL(`../src/i18n/locales/${code}/common.json`, import.meta.url), "utf8"),
    );
    const copy = messages.thread.compaction;
    await page.addInitScript((locale) => localStorage.setItem("nanobot.locale", locale), code);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let history: ThreadProjectionEvent[] = [{ event: "context_compaction", chat_id: "answer-order",
      compaction_id: "legacy", phase: "succeeded", created_at_ms: 100,
      projection_id: "legacy", turn_id: "legacy-turn", turn_seq: 1 }];
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
    await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
    await page.route("**/api/sessions/*/webui-thread?*", (route) => route.fulfill({ json: {
      schemaVersion: 3, projection: "events", has_more: false,
      events: decodeURIComponent(route.request().url()).includes("websocket:answer-order/") ? history : [],
    } }));
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
    await expect.poll(() => attached.has("answer-order")).toBe(true);
    const notices = page.locator("[data-context-compaction]");
    await expect(notices).toHaveCount(1);
    await expect(notices.first()).toHaveText(copy.succeeded);
    await expect(notices.first()).not.toHaveAttribute("role", "status");
    for (const [index, reason] of reasons.entries()) {
      const start: ThreadProjectionEvent = { event: "context_compaction", chat_id: "answer-order",
        compaction_id: reason, phase: "started", reason,
        projection_id: `${reason}-start`, turn_id: `${reason}-turn`, turn_seq: 1 };
      socket.send(JSON.stringify(start));
      const notice = notices.nth(index + 1);
      await expect(notices).toHaveCount(index + 2);
      await expect(notice).toHaveText(copy.reasons[reason].started);
      await expect(notice).toHaveAttribute("aria-busy", "true");
      const handle = await notice.elementHandle();
      const phase = phases[index === 3 ? 1 : index + 1]!;
      const finish = { ...start, phase, projection_id: `${reason}-finish`, turn_seq: 2 };
      socket.send(JSON.stringify(finish));
      await expect(notice).toHaveText(copy.reasons[reason][phase]);
      await expect(notice).toHaveAttribute("aria-busy", "false");
      expect(await notice.evaluate((node, original) => node === original, handle)).toBe(true);
      await expect(notices).toHaveCount(index + 2);
      history = [...history, start, finish];
    }
    const text = await notices.allTextContents();
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(notices).toHaveCount(0);
    await page.getByRole("button", { name: "Switch topic" }).click();
    await expect(notices).toHaveText(text);
    await page.reload();
    await expect(notices).toHaveText(text);
    await expect(page.locator('[data-context-compaction][role="status"]')).toHaveCount(0);
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => document.documentElement.classList.toggle("dark", value === "dark"), theme);
      expect(await page.locator("html").evaluate((node) => node.classList.contains("dark"))).toBe(theme === "dark");
      await expect(notices).toHaveText(text);
      for (const width of [390, 1280]) {
        await page.setViewportSize({ width, height: 900 });
        expect(await notices.evaluateAll((nodes) => nodes.every((node) => {
          const rect = node.getBoundingClientRect();
          return rect.left >= 0 && rect.right <= innerWidth && node.scrollWidth <= node.clientWidth;
        }))).toBe(true);
        await page.screenshot({ path: info.outputPath(`compaction-${code}-${theme}-${width}.png`) });
      }
    }
    expect(errors).toEqual([]);
  });
}
