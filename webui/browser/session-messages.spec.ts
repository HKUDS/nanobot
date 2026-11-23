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

      const layout = await page.getByRole("main", { name: "Session messages" }).evaluate((main) => {
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

      const row = page.locator("[data-thread-display-unit]").filter({ has: page.getByText("@mira", { exact: true }) });
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
        await copy.hover();
      }
      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await copy.click();
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("Looks good.");
    });
  }
}
