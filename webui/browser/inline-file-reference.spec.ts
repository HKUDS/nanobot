import { expect, test } from "@playwright/test";

const references = [
  "notes/ready.md",
  `notes/${"long directory/".repeat(16)}report.md`,
  String.raw`C:\Users\reader\My Docs\report.md`,
  "pytest tests/test_agent.py",
  "cat  \t~/My Docs/report.md",
  "这是一段说明文字，最后引用 /tmp/sample.txt",
  "notes/chart.png",
  `notes/${"segment".repeat(30)}.md`,
];

for (const { width, theme } of [{ width: 390, theme: "dark" }, { width: 1024, theme: "light" }]) {
  test(`inferred files retain readable and copyable source at ${width}px`, async ({ page, context }, info) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.addInitScript(theme => {
      localStorage.setItem("nanobot.locale", "en");
      localStorage.setItem("nanobot-webui.theme", theme);
    }, theme);
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/browser/fixture.html?case=inline-file-reference");
    const message = page.getByRole("region", { name: "File references" });
    const files = message.getByTestId("inline-file-path");
    await expect(files).toHaveCount(references.length + 1);
    expect(await page.locator("html").evaluate(node => node.classList.contains("dark"))).toBe(theme === "dark");

    for (const state of ["streaming", "complete"]) {
      if (state === "complete") await page.getByRole("button", { name: "Complete message" }).click();
      for (const [index, text] of references.entries()) {
        const reference = files.nth(index);
        expect(await reference.textContent()).toBe(text);
        expect(await reference.locator("xpath=ancestor::p").textContent()).toBe(`Before ${text} after.`);
        const code = reference.locator("code");
        const metrics = await code.evaluate(node => {
          const paragraph = node.closest("p")!;
          const bounds = paragraph.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(node);
          const selection = window.getSelection()!;
          selection.removeAllRanges();
          selection.addRange(range);
          return {
            selected: selection.toString(),
            lines: node.getClientRects().length,
            contained: [...node.getClientRects()].every(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1),
          };
        });
        expect(metrics.selected).toBe(text);
        expect(metrics.contained).toBe(true);
        if (index === 1 || index === 7) expect(metrics.lines).toBeGreaterThan(1);
        if (state === "complete" && [1, 2, 4].includes(index)) {
          await page.keyboard.press("ControlOrMeta+c");
          expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(text);
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await expect(files.last()).toHaveText("Short report");
    }
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await page.screenshot({ path: info.outputPath(`inline-files-${theme}.png`), fullPage: true });

    await files.nth(1).click();
    await expect(page.getByLabel("Opened file")).toHaveText(references[1]);
    await expect(page.getByLabel("Opened file")).toHaveAttribute("data-count", "1");
    await files.first().focus();
    await files.first().press("Enter");
    await expect(page.getByLabel("Opened file")).toHaveText(references[0]);
    await expect(page.getByLabel("Opened file")).toHaveAttribute("data-count", "2");
    await files.nth(3).click();
    await expect(files.nth(3)).not.toHaveAttribute("role");
    await expect(page.getByLabel("Opened file")).toHaveAttribute("data-count", "2");

    await files.first().focus();
    await files.first().press("Shift+F10");
    await page.getByRole("menuitem", { name: "Copy absolute path", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(references[0]);
    await files.nth(6).hover();
    await expect(page.getByTestId("file-image-quick-look").locator("img")).toBeVisible();
    expect(errors).toEqual([]);
  });
}
