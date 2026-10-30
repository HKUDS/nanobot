import { expect, test, type Page } from "@playwright/test";
import { canonicalThreadPayload } from "../src/tests/thread-test-payload";

const history = canonicalThreadPayload({
  schemaVersion: 3,
  messages: [
    { id: "question", role: "user", content: "Explain stable layout.", createdAt: 1_700_000_000_000 },
    {
      id: "answer", role: "assistant", createdAt: 1_700_000_001_000,
      content: Array.from({ length: 25 }, (_, index) =>
        `## Section ${index + 1}\n\nA completed answer stays in place while the next draft is edited. 中文与 English 混排，保持阅读位置稳定。`,
      ).join("\n\n"),
    },
  ],
});

async function openThread(page: Page) {
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.route("**/api/commands", route => route.fulfill({ json: { commands: [] } }));
  await page.route("**/api/sessions/*/webui-thread?*", route => route.fulfill({ json: history }));
  await page.goto("/browser/fixture.html?case=thread-loading");
  await expect(page.getByRole("heading", { name: "Section 25", exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("Next steps:\n1. Check layout\n2. ");
  await input.focus();
  const scroller = page.getByTestId("thread-message-region");
  await expect.poll(() => scroller.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThanOrEqual(1);
  return { input, scroller };
}

async function sampleWhileTyping(page: Page) {
  return page.evaluate(async () => {
    const scroller = document.querySelector<HTMLElement>(".thread-message-viewport")!;
    const input = document.querySelector<HTMLTextAreaElement>("textarea")!;
    const baseline = { top: scroller.scrollTop, inputHeight: input.clientHeight, viewportHeight: scroller.clientHeight };
    const samples: typeof baseline[] = [];
    let active = true;
    const sample = () => {
      samples.push({ top: scroller.scrollTop, inputHeight: input.clientHeight, viewportHeight: scroller.clientHeight });
      if (active) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
    return new Promise<{ baseline: typeof baseline; samples: typeof samples }>(resolve => {
      document.addEventListener("typing-sample-end", async () => {
        await new Promise(requestAnimationFrame);
        active = false;
        resolve({ baseline, samples });
      }, { once: true });
    });
  });
}

for (const width of [1500, 390]) for (const readingHistory of [false, true]) {
  test(`typing preserves every rendered transcript position at ${width}px ${readingHistory ? "in history" : "at the tail"}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 940 });
    const { input, scroller } = await openThread(page);
    if (readingHistory) {
      const box = (await scroller.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(0, -350);
      await expect.poll(() => scroller.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeGreaterThan(300);
    }
    const sampling = sampleWhileTyping(page);
    await input.pressSequentially("abcdefghijklmnopqrstuvwxyz", { delay: 75 });
    await page.evaluate(() => document.dispatchEvent(new Event("typing-sample-end")));
    const { baseline, samples } = await sampling;
    expect(samples.length).toBeGreaterThan(10);
    expect(Math.max(...samples.map(sample => Math.abs(sample.top - baseline.top)))).toBeLessThanOrEqual(1);
    expect(samples.every(sample => sample.inputHeight === baseline.inputHeight && sample.viewportHeight === baseline.viewportHeight)).toBe(true);
  });
}

test("autosizing still grows, caps and shrinks the real input", async ({ page }) => {
  const { input, scroller } = await openThread(page);
  const initialHeight = await input.evaluate(node => node.clientHeight);
  await input.fill(Array.from({ length: 6 }, (_, index) => `Line ${index + 1}`).join("\n"));
  await expect.poll(() => input.evaluate(node => node.clientHeight)).toBeGreaterThan(initialHeight);
  expect(await input.evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
  await input.fill(Array.from({ length: 20 }, (_, index) => `Line ${index + 1}`).join("\n"));
  await expect(input).toHaveCSS("height", "260px");
  expect(await input.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
  await input.press("Control+End");
  await expect.poll(() => input.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
  await input.fill("Short draft");
  await expect.poll(() => input.evaluate(node => node.clientHeight)).toBeLessThan(initialHeight);
  expect(await input.evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
  await expect.poll(() => scroller.evaluate(node => node.scrollHeight - node.clientHeight - node.scrollTop)).toBeLessThanOrEqual(1);
});

test("Chromium IME composition and commit keep the transcript stationary", async ({ page }) => {
  const { input } = await openThread(page);
  const original = await input.inputValue();
  const cdp = await page.context().newCDPSession(page);
  const sampling = sampleWhileTyping(page);
  for (const text of ["z", "zhong", "zhongwen"]) {
    await cdp.send("Input.imeSetComposition", { text, selectionStart: text.length, selectionEnd: text.length });
    await page.evaluate(() => new Promise(requestAnimationFrame));
  }
  await expect(input).toHaveValue(`${original}zhongwen`);
  await cdp.send("Input.insertText", { text: "中文" });
  await expect(input).toHaveValue(`${original}中文`);
  await page.evaluate(() => document.dispatchEvent(new Event("typing-sample-end")));
  const { baseline, samples } = await sampling;
  expect(samples.length).toBeGreaterThan(0);
  expect(Math.max(...samples.map(sample => Math.abs(sample.top - baseline.top)))).toBeLessThanOrEqual(1);
  expect(samples.every(sample => sample.inputHeight === baseline.inputHeight)).toBe(true);
  await cdp.detach();
});


test("multiline drafts resize after reading typography changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=typography");
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("First line\nSecond line\nThird line");
  const standardHeight = await input.evaluate(node => node.clientHeight);
  const sizes = [
    ["large", "Large reading text", 20],
    ["small", "Small reading text", 16],
    ["standard", "Standard reading text", 18],
  ] as const;
  for (const [size, label, fontSize] of sizes) {
    await page.getByRole("radio", { name: label, exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-reading-text-size", size);
    await expect(input).toHaveCSS("font-size", `${fontSize}px`);
    expect(await input.evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
    const height = await input.evaluate(node => node.clientHeight);
    if (size === "large") expect(height).toBeGreaterThan(standardHeight);
    else if (size === "small") expect(height).toBeLessThan(standardHeight);
    else expect(height).toBe(standardHeight);
  }
});
