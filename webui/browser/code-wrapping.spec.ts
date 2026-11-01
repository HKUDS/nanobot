import { expect, test } from "@playwright/test";

test("numbered Markdown code keeps mixed text flowing after stream completion", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/browser/fixture.html?case=code-wrapping");
  const source = await page.getByRole("textbox", { name: "Code source" }).inputValue();
  const block = page.locator('[data-language="markdown"]');
  await expect(block.getByTestId("plain-code-fallback")).toBeVisible();
  await page.getByRole("button", { name: "Complete message" }).click();
  const pre = block.locator("pre");
  await expect(pre.locator(".token").first()).toBeVisible();
  await expect(pre.locator(".linenumber")).toHaveText(source.split("\n").map((_, index) => String(index + 1)));

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => document.fonts.ready);
    await expect.poll(() => pre.evaluate(element => {
      const phrase = "启动器在";
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      let node: Node | null;
      while ((node = walker.nextNode())) {
        const start = node.textContent!.indexOf(phrase);
        if (start < 0) continue;
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, start + 1);
        const first = range.getBoundingClientRect();
        range.setStart(node, start + phrase.length - 1);
        range.setEnd(node, start + phrase.length);
        const last = range.getBoundingClientRect();
        return {
          horizontal: Math.abs(first.y - last.y) < 1 && last.x > first.x,
          contained: element.scrollWidth <= element.clientWidth + 1,
        };
      }
      throw new Error("The Chinese phrase is missing from the rendered source");
    })).toEqual({ horizontal: true, contained: true });
  }

  await block.getByRole("button", { name: "Copy code", exact: true }).click();
  await expect.poll(async () => (await page.evaluate(() => navigator.clipboard.readText())).replaceAll("\r\n", "\n")).toBe(source);
});
