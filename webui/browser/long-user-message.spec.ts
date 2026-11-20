import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`collapses user messages exceeding half viewport height at ${width}px in ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/browser/fixture.html?case=long-user-message${theme === "dark" ? "&dark" : ""}`);

      const bubbles = page.locator("[data-user-text-bubble]");
      await expect(bubbles).toHaveCount(2);

      const shortBubble = bubbles.first();
      const longBubble = bubbles.last();

      await expect(shortBubble).not.toHaveAttribute("data-user-message-collapsible");
      await expect(shortBubble.locator("[data-user-message-toggle]")).toHaveCount(0);

      await expect(longBubble).toHaveAttribute("data-user-message-collapsible", "true");
      await expect(longBubble).toHaveAttribute("data-user-message-collapsed", "true");

      const toggle = longBubble.locator("[data-user-message-toggle]");
      const stack = longBubble.locator("[data-user-message-stack]");
      await expect(toggle).toBeVisible();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(toggle).toHaveAttribute("data-thread-disclosure", "");
      await expect(toggle).toHaveText("Show more");
      await expect(stack).toHaveAttribute("data-state", "visible");

      const collapsedMetrics = await page.evaluate(() => {
        const scroller = document.querySelector<HTMLElement>("[data-testid='thread-message-region']")!;
        const longRow = document.querySelectorAll<HTMLElement>("[data-user-text-bubble]")[1]!;
        const pill = longRow.querySelector<HTMLElement>(":scope > p")!;
        const clip = pill.querySelector<HTMLElement>("[data-user-message-clip]")!;
        const stackEl = longRow.querySelector<HTMLElement>("[data-user-message-stack]")!;
        const toggleEl = longRow.querySelector<HTMLElement>("[data-user-message-toggle]")!;
        const scrollerRect = scroller.getBoundingClientRect();
        const pillRect = pill.getBoundingClientRect();
        const stackRect = stackEl.getBoundingClientRect();
        const toggleRect = toggleEl.getBoundingClientRect();
        const clipStyle = getComputedStyle(clip);
        return {
          scrollerHeight: scrollerRect.height,
          pillHeight: pillRect.height,
          stackHeight: stackRect.height,
          clipHeight: clip.getBoundingClientRect().height,
          naturalTextHeight: clip.firstElementChild!.getBoundingClientRect().height,
          maskImage: clipStyle.maskImage || clipStyle.webkitMaskImage,
          toggleInsidePill: toggleRect.top >= pillRect.top && toggleRect.bottom <= pillRect.bottom + 1,
          toggleBottomGap: pillRect.bottom - toggleRect.bottom,
          pageOverflows: document.documentElement.scrollWidth > innerWidth,
        };
      });

      expect(collapsedMetrics.pageOverflows).toBe(false);
      expect(collapsedMetrics.naturalTextHeight).toBeGreaterThan(collapsedMetrics.scrollerHeight * 0.5);
      expect(collapsedMetrics.pillHeight).toBeLessThanOrEqual(collapsedMetrics.scrollerHeight * 0.5);
      expect(collapsedMetrics.stackHeight).toBeGreaterThan(6);
      expect(collapsedMetrics.clipHeight).toBeLessThan(collapsedMetrics.naturalTextHeight - 60);
      expect(collapsedMetrics.maskImage).toContain("linear-gradient");
      expect(collapsedMetrics.toggleInsidePill).toBe(true);
      expect(collapsedMetrics.toggleBottomGap).toBeGreaterThanOrEqual(4);

      await toggle.click();
      await expect(longBubble).not.toHaveAttribute("data-user-message-collapsed");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(toggle).toHaveText("Show less");
      await expect(stack).toHaveAttribute("data-state", "hidden");

      await expect.poll(async () => {
        return longBubble.evaluate((el) => {
          const clip = el.querySelector<HTMLElement>("[data-user-message-clip]")!;
          const stackEl = el.querySelector<HTMLElement>("[data-user-message-stack]")!;
          return Math.abs(clip.getBoundingClientRect().height - clip.firstElementChild!.getBoundingClientRect().height)
            + stackEl.getBoundingClientRect().height;
        });
      }).toBeLessThan(2);

      const expandedMetrics = await longBubble.evaluate((el) => {
        const pill = el.querySelector<HTMLElement>(":scope > p")!;
        const clip = pill.querySelector<HTMLElement>("[data-user-message-clip]")!;
        const toggleEl = el.querySelector<HTMLElement>("[data-user-message-toggle]")!;
        const clipRect = clip.getBoundingClientRect();
        const toggleRect = toggleEl.getBoundingClientRect();
        const clipStyle = getComputedStyle(clip);
        return {
          pillHeight: pill.getBoundingClientRect().height,
          maskImage: clipStyle.maskImage || clipStyle.webkitMaskImage,
          textClearsToggle: clipRect.bottom <= toggleRect.top + 1,
          pageOverflows: document.documentElement.scrollWidth > innerWidth,
        };
      });

      expect(expandedMetrics.pageOverflows).toBe(false);
      expect(expandedMetrics.pillHeight).toBeGreaterThan(collapsedMetrics.pillHeight + 100);
      expect(expandedMetrics.maskImage).toBe("none");
      expect(expandedMetrics.textClearsToggle).toBe(true);

      await toggle.click();
      await expect(longBubble).toHaveAttribute("data-user-message-collapsed", "true");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(toggle).toHaveText("Show more");
    });
  }
}

test("copies full user message text while collapsed and anchors scroll when collapsing from bottom", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/browser/fixture.html?case=long-user-message");

  const longUnit = page.locator("[data-user-prompt-id='long-user']");
  const longBubble = longUnit.locator("[data-user-text-bubble]");
  await expect(longBubble).toHaveAttribute("data-user-message-collapsed", "true");

  await longUnit.hover();
  await longUnit.getByRole("button", { name: "Message actions", exact: true }).click();
  await page.locator("[data-message-block-menu]").getByRole("button", { name: "Copy", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain("Final line sentinel");
  await page.keyboard.press("Escape");

  const toggle = longBubble.locator("[data-user-message-toggle]");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect.poll(async () => {
    return longBubble.evaluate((el) => {
      const clip = el.querySelector<HTMLElement>("[data-user-message-clip]")!;
      return Math.abs(clip.getBoundingClientRect().height - clip.firstElementChild!.getBoundingClientRect().height);
    });
  }).toBeLessThan(2);

  // Scroll the expanded bubble's top above the viewport, then collapse from the bottom toggle.
  await page.evaluate(() => {
    const scroller = document.querySelector<HTMLElement>("[data-testid='thread-message-region']")!;
    const pill = document.querySelector<HTMLElement>("[data-user-prompt-id='long-user'] [data-user-text-bubble] > p")!;
    const pillTop = scroller.scrollTop + (pill.getBoundingClientRect().top - scroller.getBoundingClientRect().top);
    scroller.scrollTop = pillTop + 260;
  });

  await toggle.click();
  await expect(longBubble).toHaveAttribute("data-user-message-collapsed", "true");

  const topVisible = await page.evaluate(() => {
    const scroller = document.querySelector<HTMLElement>("[data-testid='thread-message-region']")!;
    const pill = document.querySelector<HTMLElement>("[data-user-prompt-id='long-user'] [data-user-text-bubble] > p")!;
    return pill.getBoundingClientRect().top >= scroller.getBoundingClientRect().top;
  });
  expect(topVisible).toBe(true);
});
