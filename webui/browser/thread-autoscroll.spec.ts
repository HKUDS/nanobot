import { expect, test } from "@playwright/test";

test.use({ launchOptions: {
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  args: ["--enable-blink-features=MiddleClickAutoscroll"],
} });

test("lets native autoscroll leave the live tail and reverse after returning", async ({ page }) => {
  // A real scrolling control catches browser configurations without native autoscroll.
  await page.setContent('<div id="control" style="height:600px;overflow:auto"><div style="height:5000px">Autoscroll control</div></div>');
  await page.locator("#control").click({ button: "middle", position: { x: 200, y: 200 } });
  await page.mouse.move(200, 300);
  await expect.poll(() => page.locator("#control").evaluate((node) => node.scrollTop)).toBeGreaterThan(100);
  await page.keyboard.press("Escape");

  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=history-boundary&local=1");
  const body = page.getByTestId("thread-message-region");
  // The plain-text fallback is replaced when the lazy Markdown renderer loads.
  const tail = body.locator(".markdown-content").getByText("Cached message 279", { exact: true });
  await expect(tail).toBeVisible();
  const distanceFromBottom = () => body.evaluate((node) => node.scrollHeight - node.clientHeight - node.scrollTop);
  expect(await body.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeGreaterThan(1_000);
  await expect.poll(distanceFromBottom).toBeLessThan(1);
  await tail.click({ button: "middle" });
  const bounds = await tail.boundingBox();
  expect(bounds).not.toBeNull();
  const x = bounds!.x + bounds!.width / 2;
  const y = bounds!.y + bounds!.height / 2;

  await page.mouse.move(x, y - 100);
  await expect.poll(distanceFromBottom).toBeGreaterThan(150);
  await page.mouse.move(x, y + 100);
  await expect.poll(distanceFromBottom).toBeLessThan(1);
  await page.mouse.move(x, y - 100);
  await expect.poll(distanceFromBottom).toBeGreaterThan(150);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Scroll to bottom" })).toBeVisible();
  await page.getByRole("button", { name: "Scroll to bottom" }).click();
  await expect.poll(distanceFromBottom).toBeLessThan(1);
});
