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
  await expect(pre.locator("[data-code-token]").first()).toBeVisible();
  await expect(pre.locator("code > span > span[aria-hidden]")).toHaveText(source.split("\n").map((_, index) => String(index + 1)));

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


test("single-line inline code wraps in streaming and completed messages without losing whitespace", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=code-wrapping");
  const inline = page.getByTestId("inline-code-wrapping");
  const expected = [
    { prefix: "Before", text: `${"word ".repeat(23)}wordx` },
    { prefix: "Before", text: `${"word ".repeat(24)}x` },
    { prefix: "Spaces", text: `begin  \t${"word ".repeat(30)}end` },
    { prefix: "Token", text: "x".repeat(180) },
    { prefix: "CJK", text: "中文".repeat(70) },
    { prefix: "Short", text: "one  \ttwo" },
  ];

  for (const state of ["streaming", "complete"]) {
    if (state === "complete") await page.getByRole("button", { name: "Complete message" }).click();
    for (const width of [390, 900]) {
      await page.setViewportSize({ width, height: 900 });
      for (const [index, { prefix, text }] of expected.entries()) {
        const code = inline.locator("p").nth(index).locator("code");
        await expect(code).toHaveText(text);
        expect(await code.textContent()).toBe(text);
        const metrics = await code.evaluate(element => {
          const style = getComputedStyle(element);
          const paragraph = element.parentElement!;
          return {
            display: style.display,
            whiteSpace: style.whiteSpace,
            lines: element.getClientRects().length,
            contained: paragraph.scrollWidth <= paragraph.clientWidth + 1,
            surrounding: paragraph.textContent,
          };
        });
        expect(metrics.display).toBe("inline");
        expect(metrics.whiteSpace).toBe("break-spaces");
        expect(metrics.contained).toBe(true);
        expect(metrics.surrounding).toBe(`${prefix} ${text} after.`);
        if (width === 390 && index < 5) expect(metrics.lines).toBeGreaterThan(1);
      }
      const linkedCode = inline.locator('p a[href="https://example.com"] code');
      expect(await linkedCode.textContent()).toBe("x".repeat(180));
      const linkLayout = await linkedCode.evaluate(node => ({
        display: getComputedStyle(node).display,
        lines: node.getClientRects().length,
        contained: node.closest("p")!.scrollWidth <= node.closest("p")!.clientWidth + 1,
      }));
      expect(linkLayout.display).toBe("inline");
      expect(linkLayout.contained).toBe(true);
      if (width === 390) expect(linkLayout.lines).toBeGreaterThan(1);
      const selected = await inline.locator("p").nth(2).locator("code").evaluate(element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        return selection.toString();
      });
      expect(selected).toBe(expected[2].text);
      const shortSelected = await inline.locator("p").nth(5).locator("code").evaluate(element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        return selection.toString();
      });
      expect(shortSelected).toBe(expected[5].text);
      const table = inline.getByTestId("markdown-data-table").first();
      await expect(table.locator("code")).toHaveText(["default", "release", "private", "enabled", "compact"]);
      expect(await table.locator("code").evaluateAll(nodes => nodes.map(node => node.getClientRects().length))).toEqual([1, 1, 1, 1, 1]);
      if (width === 390) {
        expect(await table.evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
        await table.evaluate(node => { node.scrollLeft = node.scrollWidth; });
        expect(await table.evaluate(node => {
          const bounds = node.getBoundingClientRect();
          const lastCell = node.querySelector("tbody td:last-child")!.getBoundingClientRect();
          return lastCell.right <= bounds.right + 1 && lastCell.left >= bounds.left - 1;
        })).toBe(true);
      }
      const outsideCode = `begin  \t${"word ".repeat(25)}end`;
      for (const code of [
        inline.getByTestId("markdown-data-table").last().locator("code"),
        inline.locator("h2 code"),
        inline.locator("li code"),
      ]) {
        expect(await code.textContent()).toBe(outsideCode);
        const unchanged = await code.evaluate(node => {
          const range = document.createRange();
          range.selectNodeContents(node);
          const selection = window.getSelection()!;
          selection.removeAllRanges();
          selection.addRange(range);
          return { display: getComputedStyle(node).display, whiteSpace: getComputedStyle(node).whiteSpace, selected: selection.toString() };
        });
        expect(unchanged).toEqual({ display: "block", whiteSpace: "pre", selected: outsideCode });
      }
      const blocks = inline.locator("[data-language='text'] pre");
      await expect(blocks).toHaveCount(2);
      for (const [index, text] of [`${"f".repeat(180)}\nsecond line`, `${"i".repeat(180)}\nindented line two`].entries()) {
        const block = blocks.nth(index);
        const content = await block.locator("code").evaluate(node => {
          const lines = [...node.querySelectorAll(":scope > span")];
          return lines.map(line => line.children[1]?.textContent ?? "").join("\n");
        });
        expect(content).toBe(text);
        expect(await block.evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
      }
    }
  }
});


test("streaming message keeps growing inline code in its paragraph through completion", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=code-wrapping");
  const source = page.getByRole("textbox", { name: "Inline message source" });
  const message = page.getByTestId("inline-message-wrapping");

  for (const width of [390, 900]) {
    await page.setViewportSize({ width, height: 900 });
    for (const length of [1, 119, 120, 121, 122, 260]) {
      const text = "x".repeat(length);
      await source.fill(`Before \`${text}`);
      const code = message.locator("p code");
      await expect(code).toHaveText(text);
      const layout = await code.evaluate(node => ({
        display: getComputedStyle(node).display,
        lines: node.getClientRects().length,
        contained: node.parentElement!.scrollWidth <= node.parentElement!.clientWidth + 1,
      }));
      expect(layout.display).toBe("inline");
      expect(layout.contained).toBe(true);
      if (width === 390 && length === 260) expect(layout.lines).toBeGreaterThan(1);
    }
  }

  const text = `begin  \t${"word ".repeat(30)}end`;
  await source.fill(`Before \`${text}\` after.`);
  await page.getByRole("button", { name: "Complete inline message" }).click();
  await expect(message.locator("[data-assistant-selectable]")).toHaveAttribute("data-assistant-selectable", "true");
  for (const width of [390, 900]) {
    await page.setViewportSize({ width, height: 900 });
    const code = message.locator("p code");
    await expect(code).toHaveText(text);
    expect(await code.textContent()).toBe(text);
    const result = await code.evaluate(node => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
      return {
        display: getComputedStyle(node).display,
        contained: node.parentElement!.scrollWidth <= node.parentElement!.clientWidth + 1,
        selected: selection.toString(),
        paragraph: node.parentElement!.textContent,
      };
    });
    expect(result).toEqual({ display: "inline", contained: true, selected: text, paragraph: `Before ${text} after.` });
  }
});


test("message lists and quotes retain their existing whitespace and scrolling", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=code-wrapping");
  const source = page.getByRole("textbox", { name: "Inline message source" });
  const message = page.getByTestId("inline-message-wrapping");
  const text = `begin  \t${"word ".repeat(25)}end`;
  const cases = [
    { markdown: `- List \`${text}\` after`, target: "li", parent: "LI" },
    { markdown: `- List \`${text}\` after\n\n- Second`, target: "li", parent: "P" },
    { markdown: `> List \`${text}\` after`, target: "blockquote", parent: "P" },
    { markdown: `- List \`one  \ttwo\` after\n\n- Second`, target: "li", parent: "P", short: true },
    { markdown: "> List `one  \ttwo` after", target: "blockquote", parent: "P", short: true },
  ];

  for (const width of [390, 900]) {
    await page.setViewportSize({ width, height: 900 });
    for (const item of cases) {
      await source.fill(item.markdown);
      const target = message.locator(item.target).first();
      const code = target.locator("code");
      const codeText = item.short ? "one  \ttwo" : text;
      await expect(code).toHaveText(codeText);
      const result = await code.evaluate(node => {
        const target = node.closest("li, blockquote")!;
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        const style = getComputedStyle(node);
        return {
          text: node.textContent, parent: node.parentElement!.tagName,
          display: style.display, whiteSpace: style.whiteSpace, overflowX: style.overflowX,
          lines: node.getClientRects().length, scrollable: node.scrollWidth > node.clientWidth,
          selected: selection.toString(),
        };
      });
      expect(result).toEqual(item.short ? {
        text: codeText, parent: item.parent, display: "inline", whiteSpace: "normal", overflowX: "visible",
        lines: 1, scrollable: false, selected: "List one two after",
      } : {
        text: codeText, parent: item.parent, display: "block", whiteSpace: "pre", overflowX: "auto",
        lines: 1, scrollable: true, selected: `List\n${text}\nafter`,
      });
    }
  }
  await source.fill(`> List \`${text}\` after`);
  await page.getByRole("button", { name: "Complete inline message" }).click();
  await expect(message.locator("[data-assistant-selectable]")).toHaveAttribute("data-assistant-selectable", "true");
  const quote = message.locator("blockquote code");
  await expect(quote).toHaveText(text);
  expect(await quote.evaluate(node => ({
    display: getComputedStyle(node).display,
    whiteSpace: getComputedStyle(node).whiteSpace,
    overflowX: getComputedStyle(node).overflowX,
  }))).toEqual({ display: "block", whiteSpace: "pre", overflowX: "auto" });
});

test("inline code uses a translucent surface over a custom background", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=code-wrapping");
  const code = page.getByTestId("inline-code-wrapping").locator(".markdown-inline-code").first();
  await expect(code).toBeVisible();
  const original = await code.evaluate(element => getComputedStyle(element).backgroundColor);
  await page.evaluate(() => { document.documentElement.dataset.customBackground = ""; });
  for (let i = 0; i < 2; i++) {
    await expect(code).toHaveCSS("background-color", /rgba\(.+, 0\.45\)/);
    await page.evaluate(() => document.documentElement.classList.toggle("dark"));
  }
  await page.evaluate(() => { delete document.documentElement.dataset.customBackground; });
  await expect(code).toHaveCSS("background-color", original);
});
