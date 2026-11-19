import { expect, test } from "@playwright/test";

test("inferred files wrap without losing copy text or preview actions", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=inline-file-reference");
  const files = page.getByRole("region", { name: "File references" }).getByTestId("inline-file-path");
  await expect(files).toHaveCount(9);

  for (const state of ["streaming", "complete"]) {
    if (state === "complete") await page.getByRole("button", { name: "Complete message" }).click();
    for (const width of [390, 1024]) {
      await page.setViewportSize({ width, height: 1000 });
      // Spaced and unbroken long paths exercise the two wrapping cases.
      for (const index of [1, 7]) {
        const metrics = await files.nth(index).locator("code").evaluate(node => {
          const bounds = node.closest("p")!.getBoundingClientRect();
          return {
            lines: node.getClientRects().length,
            contained: [...node.getClientRects()].every(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1),
          };
        });
        expect(metrics.lines).toBeGreaterThan(1);
        expect(metrics.contained).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }

  for (const [index, text] of [
    [1, `notes/${"long directory/".repeat(16)}report.md`],
    [2, String.raw`C:\Users\reader\My Docs\report.md`],
    [4, "cat  \t~/My Docs/report.md"],
  ] as const) {
    const selected = await files.nth(index).locator("code").evaluate(node => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
      return selection.toString();
    });
    expect(selected).toBe(text);
    await page.keyboard.press("ControlOrMeta+c");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text);
  }
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  await expect(files.last()).toHaveText("Short report");

  await files.nth(1).click();
  await expect(page.getByLabel("Opened file")).toHaveText(`notes/${"long directory/".repeat(16)}report.md`);
  await files.first().press("Enter");
  await expect(page.getByLabel("Opened file")).toHaveText("notes/ready.md");
  await files.first().press("Shift+F10");
  await page.getByRole("menuitem", { name: "Copy absolute path", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("notes/ready.md");
  await files.nth(6).hover();
  await expect(page.getByTestId("file-image-quick-look").locator("img")).toBeVisible();
});
