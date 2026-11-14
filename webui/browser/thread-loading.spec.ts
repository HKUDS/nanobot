import { expect, test } from "@playwright/test";
import { canonicalThreadPayload } from "../src/tests/thread-test-payload";

const history = canonicalThreadPayload({
  schemaVersion: 3,
  messages: [
    { id: "question", role: "user", content: "Preview question", createdAt: 1_700_000_000_000 },
    { id: "answer", role: "assistant", content: "Preview answer", createdAt: 1_700_000_001_000 },
  ],
});

for (const width of [314, 390, 1440]) for (const dark of [false, true]) {
  test(`history skeleton keeps live controls in place at ${width}px ${dark ? "dark" : "light"}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 314 ? 647 : 844 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => { localStorage.setItem("nanobot.locale", "en"); });
    await page.route("**/api/commands", (route) => route.fulfill({ json: { commands: [] } }));
    let releaseHistory!: () => void;
    const historyGate = new Promise<void>((resolve) => { releaseHistory = resolve; });
    await page.route("**/api/sessions/*/webui-thread?*", async (route) => {
      await historyGate;
      await route.fulfill({ json: history });
    });
    await page.goto(`/browser/fixture.html?case=thread-loading${dark ? "&dark" : ""}`);
    const loading = page.getByRole("status", { name: "Loading conversation…" });
    await expect(loading).toBeVisible();
    await expect(loading).toHaveAttribute("aria-busy", "true");
    await expect(page.getByRole("textbox", { name: "Message input" })).toBeEnabled();
    await expect(page.locator(".startup-shell")).toHaveCount(0);
    await expect(loading.locator("[aria-hidden] > div")).toHaveCount(3);
    await page.evaluate(async () => { await document.fonts.ready; });
    const header = await page.getByTestId("thread-header").boundingBox();
    const composer = page.locator(".thread-composer-surface");
    const before = (await composer.boundingBox())!;
    const loadingBox = (await loading.boundingBox())!;
    expect(loadingBox.width).toBeGreaterThan(0);
    expect(loadingBox.y + loadingBox.height).toBeLessThanOrEqual(before.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    const pulse = loading.locator("[aria-hidden]");
    await expect(pulse).toHaveCSS("animation-name", "pulse");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(pulse).toHaveCSS("animation-name", "none");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.evaluate(() => {
      const layout = document.querySelector(".thread-layout")!;
      const transitions: (string | null)[] = [];
      Object.defineProperty(window, "loadingLayoutTransitions", { value: transitions });
      new MutationObserver((records) => {
        for (const record of records) transitions.push(record.oldValue);
      }).observe(layout, { attributes: true, attributeFilter: ["data-layout"], attributeOldValue: true });
    });

    await page.getByRole("textbox", { name: "Message input" }).fill("Draft survives loading");
    releaseHistory();
    await expect(page.getByText("Preview answer", { exact: true })).toBeVisible();
    await expect(loading).toHaveCount(0);
    expect(await page.evaluate(() => (window as Window & { loadingLayoutTransitions?: (string | null)[] }).loadingLayoutTransitions)).not.toContain("hero");
    await expect(page.getByRole("textbox", { name: "Message input" })).toHaveValue("Draft survives loading");
    const after = (await composer.boundingBox())!;
    for (const dimension of ["x", "y", "width", "height"] as const) {
      expect(Math.abs(before[dimension] - after[dimension]), dimension).toBeLessThanOrEqual(1);
    }
    expect(await page.getByTestId("thread-header").boundingBox()).toEqual(header);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    expect(errors).toEqual([]);
  });
}
