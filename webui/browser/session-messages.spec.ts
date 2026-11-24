import { expect, test } from "@playwright/test";

for (const theme of ["light", "dark"] as const) {
  for (const width of [1280, 390]) {
    test(`cross-session bubbles keep their source and layout at ${width}px in ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((dark) => document.documentElement.classList.toggle("dark", dark), theme === "dark");
      await page.goto("/browser/fixture.html?case=session-messages");
      const incoming = page.locator("[data-session-message]");
      await expect(incoming).toHaveCount(2);
      await expect(incoming.first().getByText("@mira", { exact: true })).toBeVisible();
      await expect(incoming.first().getByText("Looks good.", { exact: true })).toBeVisible();
      await expect(incoming.last().locator("strong")).toHaveText("Review notes");
      await expect(incoming.last().locator("li")).toHaveCount(2);
      await expect(incoming.last().getByRole("link", { name: "Release notes" })).toHaveAttribute("href", "https://example.com/release-notes");
      const code = incoming.last().locator("pre");
      await expect(code).toBeVisible();

      const pane = page.locator('main[aria-label="Session messages"]');
      const row = pane.locator("[data-thread-display-unit]").filter({ has: page.getByText("@mira", { exact: true }) });
      const menu = row.getByRole("button", { name: "Message actions" });
      if (width >= 768) {
        await pane.evaluate(node => { node.style.maxWidth = "550px"; });
        await page.evaluate(() => { document.documentElement.style.fontSize = "20px"; });
        await menu.click();
        const sheet = page.getByRole("dialog", { name: "Message actions" });
        await expect(sheet).toBeVisible();
        await page.evaluate(() => document.documentElement.style.removeProperty("font-size"));
        await pane.evaluate(node => { node.style.maxWidth = "none"; });
        await expect(sheet).toBeHidden();
      }
      const layout = await pane.evaluate((main) => {
        const rows = [...main.querySelectorAll<HTMLElement>("[data-session-message]")];
        const own = main.querySelector<HTMLElement>("[data-user-text-bubble] > p")!;
        const ownStyle = getComputedStyle(own);
        const ownRect = own.getBoundingClientRect();
        const threadRow = own.closest<HTMLElement>("[data-thread-display-unit]")!;
        const rowStyle = getComputedStyle(threadRow);
        const rowRect = threadRow.getBoundingClientRect();
        return {
          left: rowRect.left + parseFloat(rowStyle.paddingLeft),
          right: rowRect.right - parseFloat(rowStyle.paddingRight),
          available: threadRow.clientWidth - parseFloat(rowStyle.paddingLeft) - parseFloat(rowStyle.paddingRight),
          ownRight: ownRect.right,
          ownBackground: ownStyle.backgroundColor,
          ownRadius: ownStyle.borderRadius,
          ownPadding: ownStyle.padding,
          pageOverflows: document.documentElement.scrollWidth > innerWidth,
          bubbles: rows.map((row) => {
            const bubble = row.querySelector<HTMLElement>("[data-assistant-selectable]")!.parentElement!;
            const style = getComputedStyle(bubble);
            const rect = bubble.getBoundingClientRect();
            const handle = row.firstElementChild!.firstElementChild!.getBoundingClientRect();
            const body = bubble.querySelector("[data-assistant-selectable]")!.getBoundingClientRect();
            return { left: rect.left, top: rect.top, width: rect.width, background: style.backgroundColor,
              radius: style.borderRadius, padding: style.padding, handleBottom: handle.bottom,
              handleLeft: handle.left, bodyLeft: body.left };
          }),
        };
      });
      expect(layout.pageOverflows).toBe(false);
      expect(Math.abs(layout.ownRight - layout.right)).toBeLessThan(1);
      expect(layout.bubbles[0].width).toBeLessThan(layout.bubbles[1].width);
      for (const bubble of layout.bubbles) {
        expect(Math.abs(bubble.left - layout.left)).toBeLessThan(1);
        expect(bubble.width).toBeLessThanOrEqual(Math.min(layout.available * 0.85, 576) + 1);
        expect(bubble.background).toBe(layout.ownBackground);
        expect(bubble.radius).toBe(layout.ownRadius);
        expect(bubble.padding).toBe(layout.ownPadding);
        expect(bubble.handleBottom).toBeLessThan(bubble.top);
        expect(Math.abs(bubble.handleLeft - bubble.bodyLeft)).toBeLessThan(1);
      }

      const copy = row.getByRole("button", { name: "Copy", exact: true });
      if (width >= 768) {
        const side = row.locator("[data-message-side-actions]");
        await expect(side).toHaveCSS("opacity", "0");
        const before = await incoming.first().boundingBox();
        await incoming.first().hover();
        await expect(side).toHaveCSS("opacity", "1");
        expect(await incoming.first().boundingBox()).toEqual(before);
        const bounds = (await side.boundingBox())!;
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(layout.left);
        for (const message of [incoming.first(), page.locator("[data-assistant-message]").last()]) {
          const { firstLineOffset, timestampIndent } = await message.evaluate((node) => {
            const firstLine = node.querySelector(".markdown-content p")!;
            const icon = node.querySelector("[data-message-block-copy-action] svg")!.getBoundingClientRect();
            const time = node.querySelector("[data-message-hover-time]")!.getBoundingClientRect();
            return {
              firstLineOffset: icon.y + icon.height / 2 - (firstLine.getBoundingClientRect().y + parseFloat(getComputedStyle(firstLine).lineHeight) / 2),
              timestampIndent: time.x - icon.x,
            };
          });
          expect(Math.abs(firstLineOffset)).toBeLessThan(1);
          expect(Math.abs(timestampIndent)).toBeLessThan(1);
        }
        const time = side.getByRole("time");
        await time.hover();
        await expect(page.getByRole("tooltip")).toBeVisible();
        await time.click();
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await copy.hover();
      }
      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await copy.click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("Looks good.");
      if (width >= 768) {
        await pane.evaluate(node => { node.style.maxWidth = "550px"; });
        await expect(menu).toHaveAttribute("aria-expanded", "false");
      }
    });
  }
}

test("triggered replies keep the ordinary reply column with and without side actions visible", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/browser/fixture.html?case=session-messages");
  const pane = page.getByRole("main", { name: "Session messages" });
  await pane.evaluate(node => { node.style.maxWidth = "1000px"; });
  const replies = pane.getByRole("paragraph");
  const ordinary = replies.filter({ hasText: "Thanks, I will keep those details." });
  const triggered = replies.filter({ hasText: "The scheduled update is ready." });
  const side = pane.locator("[data-message-side-actions]").filter({ has: page.locator("[data-automation-trigger]") });
  await expect(side).toHaveCSS("opacity", "0");
  const left = (await ordinary.boundingBox())!.x;
  expect((await triggered.boundingBox())!.x).toBeCloseTo(left, 0);
  await triggered.hover();
  await expect(side).toHaveCSS("opacity", "1");
  const buttons = side.getByRole("button");
  await expect(buttons).toHaveCount(4);
  await expect(buttons.nth(0)).toHaveAccessibleName("Copy");
  await expect(buttons.nth(1)).toHaveAccessibleName(/Release fallback model/);
  await expect(buttons.nth(2)).toHaveAccessibleName("New chat from here");
  await expect(buttons.nth(3)).toHaveAttribute("data-message-block-activity-action", "true");
  const [copy, source, fork, activity] = await buttons.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
  expect(source.top).toBeCloseTo(copy.top, 0);
  expect(copy.right).toBeLessThanOrEqual(source.left);
  expect(source.right).toBeLessThanOrEqual(fork.left);
  expect(fork.right).toBeLessThanOrEqual(activity.left);
  expect(fork.top).toBeCloseTo(copy.top, 0);
  expect(activity.top).toBeCloseTo(copy.top, 0);
  const rail = (await side.boundingBox())!;
  expect(rail.x).toBeGreaterThanOrEqual((await pane.boundingBox())!.x);
  expect(copy.left).toBeGreaterThanOrEqual(rail.x);
  expect(activity.right).toBeLessThanOrEqual(rail.x + rail.width);
  expect(rail.x + rail.width).toBeLessThanOrEqual(left);
  expect((await triggered.boundingBox())!.x).toBeCloseTo(left, 0);
  await side.locator("[data-automation-trigger]").focus();
  await expect(page.getByRole("tooltip")).toHaveText("Release monitor");
});
