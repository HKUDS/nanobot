import { expect, test, type Locator } from "@playwright/test";

test.use({ reducedMotion: "reduce" });
async function dotWidth(canvas: Locator, x: number, y: number) {
  return canvas.evaluate((element: HTMLCanvasElement, point) => {
    const scale = element.width / element.getBoundingClientRect().width;
    const pixels = element.getContext("2d")!.getImageData(Math.round((point.x - 15) * scale), Math.round(point.y * scale), Math.round(30 * scale), 1).data;
    let painted = 0;
    for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 0) painted++;
    return painted / scale;
  }, { x, y });
}

test("graph keyboard controls, pointer hit targets, pixels and replay agree", async ({ page }) => {
  await page.goto("/browser/context-graph.html?single");
  const node = page.getByRole("button", { name: "a.md", exact: true });
  await expect(node).toBeAttached();
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("About 100 tokens")).toBeVisible();
  await page.getByRole("button", { name: "Open file" }).click();
  await expect(page.locator("output")).toHaveText("/a.md");
  await page.keyboard.press("Escape");
  await expect(node).toBeFocused();
  await page.keyboard.press("Space");
  await expect(page.getByText("About 100 tokens")).toBeVisible();
  await page.keyboard.press("Escape");
  const canvas = page.locator("canvas");
  const box = (await canvas.boundingBox())!;
  let x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await expect.poll(() => dotWidth(canvas, box.width / 2, box.height / 2)).toBeGreaterThan(0);
  const radiusBefore = await dotWidth(canvas, box.width / 2, box.height / 2);
  await page.mouse.move(x + 40, y);
  await page.mouse.wheel(0, -400);
  x += 40 - 40 * Math.exp(0.8);
  await expect.poll(() => dotWidth(canvas, x - box.x, box.height / 2)).toBeGreaterThan(0);
  expect(Math.abs(await dotWidth(canvas, x - box.x, box.height / 2) - radiusBefore)).toBeLessThanOrEqual(1);
  await page.mouse.click(x + 11, y);
  await expect(page.getByText("About 100 tokens")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.mouse.click(x + 15, y);
  await expect(page.getByText("About 100 tokens")).toHaveCount(0);
  await page.mouse.move(x, y); await page.mouse.down();
  await page.mouse.move(x + 50, y + 30, { steps: 5 }); await page.mouse.up();
  await expect(page.getByText("About 100 tokens")).toHaveCount(0);
  await expect.poll(() => dotWidth(canvas, x - box.x + 50, box.height / 2 + 30)).toBeGreaterThan(0);
  const replay = page.getByRole("button", { name: "Play context history" });
  await replay.click();
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
  await expect(replay).toBeDisabled();
  await expect(replay).toBeEnabled();
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
});

test.describe("touch graph", () => {
  test.use({ viewport: { width: 390, height: 740 }, hasTouch: true });
  test("recovers batched drawer visibility, replays and opens a file by touch", async ({ page }) => {
    await page.addInitScript(() => {
      const NativeObserver = window.IntersectionObserver;
      window.IntersectionObserver = class extends NativeObserver {
        constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
          super((entries, observer) => {
            // Captured on a real drawer entrance under CPU throttling: the
            // offscreen record and subsequent onscreen record share a callback.
            const latest = entries[entries.length - 1];
            callback(latest.isIntersecting
              ? [{ ...latest, isIntersecting: false }, ...entries]
              : entries, observer);
          }, options);
        }
      };
    });
    await page.goto("/browser/context-graph.html?single&drawer");
    await page.getByTestId("composer-context-usage").tap();
    const canvas = page.locator("canvas");
    const box = (await canvas.boundingBox())!;
    await expect.poll(() => dotWidth(canvas, box.width / 2, box.height / 2)).toBeGreaterThan(0);
    const replay = page.getByRole("button", { name: "Play context history" });
    await replay.click();
    await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    await expect(replay).toBeEnabled();
    await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    const settledBox = (await canvas.boundingBox())!;
    await page.touchscreen.tap(settledBox.x + settledBox.width / 2, settledBox.y + settledBox.height / 2);
    const openFile = page.getByRole("button", { name: "Open file", exact: true });
    await expect(openFile).toBeVisible();
    await openFile.tap();
    await expect(page.locator("output")).toHaveText("/a.md");
    await expect(page.getByTestId("context-sidebar")).toHaveCount(0);
  });
  test("keeps a 44px touch target and redraws on theme changes", async ({ page }) => {
    await page.goto("/browser/context-graph.html?single");
    const node = page.getByRole("button", { name: "a.md", exact: true });
    await expect(node).toBeAttached();
    const canvas = page.locator("canvas");
    const box = (await canvas.boundingBox())!;
    await expect.poll(() => dotWidth(canvas, box.width / 2, box.height / 2)).toBeGreaterThan(0);
    const color = () => canvas.evaluate((element: HTMLCanvasElement) => Array.from(element.getContext("2d")!.getImageData(element.width / 2, element.height / 2, 1, 1).data));
    const before = await color();
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await expect.poll(color).not.toEqual(before);
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    await page.touchscreen.tap(x + 21, y);
    await expect(page.getByText("About 100 tokens")).toBeVisible();
    await page.getByRole("button", { name: "Open file" }).focus();
    await page.keyboard.press("Escape");
    await expect(node).toBeFocused();
    await page.touchscreen.tap(x + 23, y);
    await expect(page.getByText("About 100 tokens")).toHaveCount(0);
  });
});


declare global {
  interface Window {
    graphDrawTrace: { arcs: number; frames: number; maxTask: number; start: number };
    pythonLabelPaints: number[];
  }
}

test.describe("normal-motion file loading", () => {
  test.use({ reducedMotion: "no-preference" });
  test("introduces a loaded Python filename after idle and again during fast history replay", async ({ page }) => {
    await page.addInitScript(() => {
      window.pythonLabelPaints = [];
      const fillText = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (...args) {
        if (args[0] === "worker.py") window.pythonLabelPaints.push(this.globalAlpha);
        return fillText.apply(this, args);
      };
    });
    await page.goto("/browser/context-graph.html?single");
    await expect(page.getByRole("button", { name: "a.md", exact: true })).toBeAttached();
    // Let the existing labels finish, then leave the stopped animation clock idle.
    await page.waitForTimeout(6500);
    await page.getByRole("button", { name: "Read Python file" }).click();
    await expect(page.getByRole("button", { name: "worker.py", exact: true })).toBeAttached();
    await expect.poll(() => page.evaluate(() => window.pythonLabelPaints.some((alpha) => alpha > 0.9))).toBe(true);
    await expect.poll(() => page.evaluate(() => {
      const alpha = window.pythonLabelPaints.at(-1) ?? 1;
      return alpha > 0 && alpha < 0.3;
    })).toBe(true);
    await page.waitForTimeout(700);
    const paints = await page.evaluate(() => window.pythonLabelPaints.length);
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.pythonLabelPaints.length)).toBe(paints);
    await page.evaluate(() => { window.pythonLabelPaints = []; });
    await page.getByRole("button", { name: "Play context history" }).click();
    await expect.poll(() => page.evaluate(() => window.pythonLabelPaints.some((alpha) => alpha > 0.9))).toBe(true);
  });
});

test("500 reduced-motion nodes settle over multiple frames and are all painted", async ({ page }) => {
  await page.addInitScript(() => {
    window.graphDrawTrace = { arcs: 0, frames: 0, maxTask: 0, start: Infinity };
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...args) { window.graphDrawTrace.arcs = 0; return clear.apply(this, args); };
    const arc = CanvasRenderingContext2D.prototype.arc;
    CanvasRenderingContext2D.prototype.arc = function (...args) { window.graphDrawTrace.arcs++; return arc.apply(this, args); };
    const count = () => { window.graphDrawTrace.frames++; requestAnimationFrame(count); };
    requestAnimationFrame(count);
    new PerformanceObserver((entries) => {
      for (const entry of entries.getEntries()) if (entry.startTime >= window.graphDrawTrace.start) window.graphDrawTrace.maxTask = Math.max(window.graphDrawTrace.maxTask, entry.duration);
    }).observe({ entryTypes: ["longtask"] });
  });
  await page.goto("/browser/context-graph.html");
  await expect(page.getByRole("button", { name: "a.md", exact: true })).toBeAttached();
  await page.evaluate(() => { window.graphDrawTrace = { arcs: 0, frames: 0, maxTask: 0, start: performance.now() }; });
  await page.getByRole("button", { name: "Load 500 nodes" }).click();
  await expect(page.getByRole("button", { name: /^file-\d+\.md$/ })).toHaveCount(500);
  await expect.poll(() => page.evaluate(() => window.graphDrawTrace.arcs), { timeout: 15000 }).toBe(500);
  const trace = await page.evaluate(() => window.graphDrawTrace);
  expect(trace.frames).toBeGreaterThan(2);
  expect(trace.maxTask).toBeLessThan(100);
});


test("node details do not pan their graph and dismiss when another graph is clicked", async ({ page }) => {
  await page.goto("/browser/context-graph.html?single&pair");
  const firstNode = page.getByRole("button", { name: "a.md", exact: true }).first();
  const firstCanvas = page.locator("canvas").first();
  const box = (await firstCanvas.boundingBox())!;
  await expect.poll(() => dotWidth(firstCanvas, box.width / 2, box.height / 2)).toBeGreaterThan(0);
  await page.mouse.move(box.x + 8, box.y + 8); await page.mouse.down();
  await page.mouse.move(box.x + 58, box.y + 8); await page.mouse.up();
  await expect.poll(() => dotWidth(firstCanvas, box.width / 2 + 50, box.height / 2)).toBeGreaterThan(0);
  await firstNode.focus();
  await page.keyboard.press("Enter");
  const details = page.getByText("About 100 tokens");
  await expect(details).toBeVisible();
  await details.click();
  await expect(details).toBeVisible();
  await details.dblclick();
  await expect(details).toBeVisible();
  expect(await dotWidth(firstCanvas, box.width / 2 + 50, box.height / 2)).toBeGreaterThan(0);
  const secondCanvas = page.getByRole("region", { name: "Second graph" }).locator("canvas");
  await secondCanvas.click({ position: { x: 8, y: 8 } });
  await expect(details).toHaveCount(0);
  await firstNode.focus();
  await page.keyboard.press("Enter");
  await expect(details).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(details).toHaveCount(0);
});
