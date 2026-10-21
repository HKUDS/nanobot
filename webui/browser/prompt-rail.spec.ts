import { expect, test } from "@playwright/test";

test("complete rail scrolls independently, jumps to unloaded history and returns to latest", async ({ page }) => {
  const reads: string[] = [];
  const prompts = Array.from({ length: 2000 }, (_, index) => ({ id: `u${index}`, preview: `Question ${index}`,
    answerPreview: "A synthetic answer", cursor: String(index), turnId: `turn${index}`, createdAt: index + 1 }));
  await page.route("**/api/sessions/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/prompts")) return route.fulfill({ json: { prompts } });
    reads.push(url.search);
    const start = Number(url.searchParams.get("after") ?? Number(url.searchParams.get("before")) - 10);
    await route.fulfill({ json: { schemaVersion: 3, projection: "events", events: Array.from({ length: 10 }, (_, offset) => [
      { event: "user_message", chat_id: "rail", projection_id: `u${start + offset}`, text: `Question ${start + offset}`, starts_turn: true },
      { event: "message", chat_id: "rail", projection_id: `a${start + offset}`, text: "Historical answer.\n\n".repeat(8) },
    ]).flat(), page: { before_cursor: String(start), after_cursor: String(start + 10), user_message_offset: start,
      has_more_before: start > 0, has_more_after: start + 10 < 2000 } } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser/fixture.html?case=rail&workbench=1");
  const rail = page.getByTestId("prompt-rail-scroll");
  const body = page.getByTestId("thread-message-region");
  await expect(rail).toBeVisible();
  // Center against the complete chat pane, not the rail's own (possibly shifted) box.
  const expectRailCentered = async () => {
    const pane = await page.getByRole("region", { name: "Workbench", exact: true }).boundingBox();
    const bounds = await rail.boundingBox();
    expect(Math.abs(bounds!.y + bounds!.height / 2 - (pane!.y + pane!.height / 2))).toBeLessThan(2);
  };
  await expectRailCentered();
  await expect.poll(() => rail.evaluate((node) => node.scrollHeight)).toBe(32024);
  expect(reads).toHaveLength(0);
  // Lazy markdown and content-visibility can change the scroll range during startup.
  await body.evaluate(async (node) => {
    let previous = -1;
    let stable = 0;
    for (let frame = 0; frame < 120 && stable < 12; frame++) {
      await new Promise(requestAnimationFrame);
      const position = node.scrollTop + node.scrollHeight;
      stable = position === previous ? stable + 1 : 0;
      previous = position;
    }
  });
  const initialBodyTop = await body.evaluate((node) => node.scrollTop);
  await rail.hover();
  await page.mouse.wheel(0, -10000);
  await expect.poll(() => rail.evaluate((node) => node.scrollTop)).toBeLessThan(25000);
  expect(await body.evaluate((node) => node.scrollTop)).toBe(initialBodyTop);
  expect(await rail.getByRole("button").count()).toBeLessThan(70);
  // Keyboard navigation reaches the beginning without mounting the whole list.
  await rail.getByRole("button").first().focus();
  await page.keyboard.press("Home");
  const first = rail.getByRole("button", { name: "Jump to message: Question 0", exact: true });
  await expect(first).toBeFocused();
  await first.press("Enter");
  await expect(body.getByText("Question 0", { exact: true })).toBeInViewport();
  expect(reads).toEqual(["?limit=24&after=0"]);
  await expect(body.getByText("Question 1999", { exact: true })).toHaveCount(0);
  for (const after of [10, 20, 30, 40]) {
    await body.hover();
    await page.mouse.wheel(0, 10000);
    await expect.poll(() => reads.some((query) => query === `?limit=24&after=${after}`)).toBe(true);
    await expect(body.getByText(`Question ${after + 9}`, { exact: true })).toBeAttached();
  }
  expect(await body.locator("[data-user-prompt-id]").count()).toBeLessThanOrEqual(30);
  await body.hover();
  await page.mouse.wheel(0, -100000);
  await expect.poll(() => reads.some((query) => query.startsWith("?limit=24&before="))).toBe(true);
  await page.getByRole("button", { name: "Scroll to bottom" }).click();
  await expect(body.getByText("Question 1999", { exact: true })).toBeVisible();
  await expect(rail.locator('[aria-current="location"]')).toBeInViewport();
  expect(await rail.evaluate((node) => getComputedStyle(node).maskImage)).toContain("linear-gradient");
  await page.screenshot({ path: "test-results/prompt-rail-long.png" });
  // Short lists remain centered in the same viewport-relative space.
  await page.goto("/browser/fixture.html?case=rail&short=1&workbench=1");
  const markers = page.getByTestId("prompt-rail-marker");
  await expect(markers).toHaveCount(5);
  await expectRailCentered();
  const bounds = await page.getByRole("region", { name: "Workbench", exact: true }).boundingBox();
  const middle = await markers.nth(2).boundingBox();
  expect(Math.abs(middle!.y + middle!.height / 2 - (bounds!.y + bounds!.height / 2))).toBeLessThan(2);
  await page.screenshot({ path: "test-results/prompt-rail-short.png" });
  // A taller composer in a shorter window must not push navigation above center.
  await page.setViewportSize({ width: 1440, height: 640 });
  await page.goto("/browser/fixture.html?case=rail&short=1&tall-composer=1&workbench=1");
  await expect(markers).toHaveCount(5);
  await expectRailCentered();
  const shortBounds = await page.getByRole("region", { name: "Workbench", exact: true }).boundingBox();
  const shortMiddle = await markers.nth(2).boundingBox();
  expect(Math.abs(shortMiddle!.y + shortMiddle!.height / 2 - (shortBounds!.y + shortBounds!.height / 2))).toBeLessThan(2);
  await expect(markers.first()).toBeInViewport();
  await expect(markers.last()).toBeInViewport();
  await page.setViewportSize({ width: 800, height: 900 });
  await page.goto("/browser/fixture.html?case=rail&short=1&workbench=1");
  await expect(rail).not.toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(rail).toBeVisible();
  await expectRailCentered();
});
