import { expect, test } from "@playwright/test";

const sourceText = (section: import("@playwright/test").Locator) => section.locator("[data-code-text], [data-highlighted]").allTextContents().then(lines => lines.join(""));

for (const dark of [false, true]) {
  for (const narrow of [false, true]) {
    test(`shared highlighting retains code and preview behavior: ${dark ? "dark" : "light"}, ${narrow ? "narrow" : "desktop"}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.setViewportSize({ width: narrow ? 390 : 1280, height: 900 });
      await page.addInitScript(theme => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, dark ? "dark" : "light");
      await page.goto("/browser/fixture.html?case=code-highlighting");
      const code = page.getByRole("region", { name: "TypeScript", exact: true });
      await expect(code.getByTestId("highlighted-code")).toBeVisible();
      const expected = 'export const result = <span className="badge">中文 😀</span>;\n';
      expect(await sourceText(code)).toBe(expected);
      for (const variable of ["keyword", "string", "property"]) {
        await expect.poll(async () => code.locator("[data-code-token]").evaluateAll((nodes, category) => {
          const probe = document.createElement("span");
          probe.style.color = `var(--code-${category})`;
          document.body.append(probe);
          const color = getComputedStyle(probe).color;
          probe.remove();
          return nodes.some(node => getComputedStyle(node).color === color);
        }, variable)).toBe(true);
      }
      const ini = page.getByRole("region", { name: "INI", exact: true });
      await expect(ini.getByTestId("highlighted-code")).toContainText("host=localhost");
      await expect(ini.locator('[data-code-token][style*="--code-comment"]')).toHaveText("; comment");
      expect(await sourceText(ini)).toBe("; comment\n[server]\nhost=localhost\n");
      await expect(page.getByRole("region", { name: "Unknown", exact: true }).getByTestId("highlighted-code")).toHaveText('<script>alert("not executable")</script>');
      await expect(page.getByRole("region", { name: "ANSI", exact: true }).getByTestId("ansi-code")).toHaveText('PASS <img src=x onerror="bad()">');
      expect(await page.locator("main script, main img").count()).toBe(0);
      for (const size of ["small", "standard", "large"]) {
        await page.evaluate(size => { document.documentElement.dataset.readingTextSize = size; }, size);
        const expectedBody = narrow ? size === "small" ? 15 : size === "large" ? 18 : 16 : size === "small" ? 16 : size === "large" ? 20 : 18;
        await expect(code.getByTestId("highlighted-code")).toHaveCSS("font-size", `${expectedBody * 0.875}px`);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
      await expect(page.locator("html")).toHaveClass(dark ? "" : "dark");
      expect(await sourceText(code)).toBe(expected);
      await page.getByRole("button", { name: "Change source", exact: true }).click();
      await expect(code.locator("[data-code-text]").first()).toHaveText(expected.replace("result", "updated").trimEnd());
      const markdown = page.getByRole("region", { name: "Markdown", exact: true });
      await page.getByRole("button", { name: "Start streaming", exact: true }).click();
      await expect(markdown.getByTestId("plain-code-fallback")).toContainText("export const result");
      await page.getByRole("button", { name: "Finish streaming", exact: true }).click();
      await expect(markdown.getByTestId("highlighted-code")).toContainText("中文 😀");
      const preview = page.getByRole("region", { name: "File preview", exact: true });
      await expect(preview.getByTestId("viewport-code-rows")).toBeVisible();
      const original = await sourceText(preview);
      expect(original).toContain("Line 519 😀");
      expect(await page.evaluate(() => "find" in window && typeof window.find === "function" && window.find("Line 519 😀"))).toBe(true);
      await page.evaluate(() => { document.getSelection()?.removeAllRanges(); document.dispatchEvent(new Event("selectionchange")); });
      const scroller = preview.locator("[data-file-preview-scroll]");
      await scroller.scrollIntoViewIfNeeded();
      await scroller.evaluate(node => { node.scrollTop = node.scrollHeight; node.scrollLeft = 120; });
      await expect(preview.locator('[data-code-chunk="15"] [data-highlighted]')).toHaveAttribute("data-highlighted", "true");
      expect(await sourceText(preview)).toBe(original);
      expect(await scroller.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
      const line = preview.locator('[data-highlighted="true"]').last();
      await line.evaluate(node => {
        const range = document.createRange(); range.selectNodeContents(node);
        const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
      });
      const selected = await page.evaluate(() => document.getSelection()?.toString());
      await scroller.evaluate(node => { node.scrollTop = 0; });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      expect(await page.evaluate(() => document.getSelection()?.toString())).toBe(selected);
      await page.evaluate(() => { document.getSelection()?.removeAllRanges(); document.dispatchEvent(new Event("selectionchange")); });
      await expect(preview.locator('[data-code-chunk="0"] [data-highlighted]')).toHaveAttribute("data-highlighted", "true");
      const beforeWidth = await scroller.evaluate(node => node.scrollWidth);
      await page.getByRole("button", { name: "Toggle wrapping", exact: true }).click();
      await expect(preview.getByTestId("highlighted-code")).toHaveCSS("white-space", "pre-wrap");
      expect(await scroller.evaluate(node => node.scrollWidth)).toBeLessThan(beforeWidth);
      expect(errors).toEqual([]);
    });
  }
}

test("large numbered code remains complete and copies original source", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=code-highlighting");
  await page.getByRole("button", { name: "Show large code", exact: true }).click();
  const section = page.getByRole("region", { name: "Large code", exact: true });
  await expect(section.getByTestId("highlighted-code")).toBeAttached();
  const expected = Array.from({ length: 1200 }, (_, index) => `const value${index} = ${index};`).join("\n");
  expect(await sourceText(section)).toBe(expected);
  await expect(section.getByTestId("highlighted-code").locator("span[aria-hidden]").last()).toHaveText("1200");
  await section.getByRole("button", { name: "Copy code", exact: true }).click();
  const clipboardText = process.platform === "win32" ? expected.replace(/\n/g, "\r\n") : expected;
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(clipboardText);
});


test("a real grammar request failure keeps complete source, controls and the application", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  const failed: string[] = [];
  const warning = page.waitForEvent("console", message => message.type() === "warning" && message.text().startsWith("Code highlighting failed."));
  await page.route(/\/ini-[^/]*\.js(?:\?|$)/, async route => {
    failed.push(route.request().url());
    await route.abort("failed");
  });
  await page.goto("/browser/fixture.html?case=code-highlighting");
  await warning;
  expect(failed).toHaveLength(1);
  const ini = page.getByRole("region", { name: "INI", exact: true });
  const source = "; comment\n[server]\nhost=localhost\n";
  await expect(ini.getByTestId("plain-code-fallback")).toHaveText(source);
  expect(await ini.getByTestId("plain-code-fallback").textContent()).toBe(source);
  await ini.getByRole("button", { name: "Copy code", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(process.platform === "win32" ? source.replace(/\n/g, "\r\n") : source);
  await page.getByRole("button", { name: "Change source", exact: true }).click();
  await expect(page.getByRole("region", { name: "TypeScript", exact: true }).getByTestId("highlighted-code")).toContainText("export const updated");
  await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
  expect(await ini.getByTestId("plain-code-fallback").textContent()).toBe(source);
});
