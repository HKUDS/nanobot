import { expect, test, type Locator } from "@playwright/test";

async function expectKeywordColor(rows: Locator) {
  await expect.poll(async () => rows.locator("span").evaluateAll(nodes => {
    const probe = document.createElement("span");
    probe.style.color = "var(--code-keyword)";
    document.body.append(probe);
    const expected = getComputedStyle(probe).color;
    probe.remove();
    return nodes.some(node => node.textContent?.trim() === "export" && getComputedStyle(node).color === expected);
  })).toBe(true);
}

async function expectTokenColor(section: Locator, text: string, variable: string) {
  await expect.poll(async () => section.locator("[data-line] span").evaluateAll((nodes, target) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${target.variable})`;
    document.body.append(probe);
    const expected = getComputedStyle(probe).color;
    probe.remove();
    return nodes.some(node => node.textContent?.trim() === target.text && getComputedStyle(node).color === expected);
  }, { text, variable })).toBe(true);
}

for (const dark of [false, true]) {
  for (const narrow of [false, true]) {
    test(`read-only diffs preserve source, colors and reading sizes: ${dark ? "dark" : "light"}, ${narrow ? "narrow" : "desktop"}`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.setViewportSize({ width: narrow ? 390 : 1280, height: 900 });
      await page.addInitScript(theme => {
        localStorage.setItem("nanobot.locale", "en");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, dark ? "dark" : "light");
      await page.goto("/browser/fixture.html?case=file-diff");
      const tsx = page.getByRole("region", { name: "Status.tsx", exact: true });
      const rows = tsx.locator("[data-code] [data-line]");
      await expect(rows).toHaveCount(5);
      await expect(rows.nth(2)).toHaveText('  return <span className="badge">old</span>;');
      await expect(rows.nth(3)).toHaveText('  return <span className="badge">ready</span>;');
      await expect(tsx.locator("[data-line][data-line-type=change-addition] [data-diff-span]")).not.toHaveCount(0);
      await expectKeywordColor(rows);
      for (const [size, wide, small] of [["small", 16, 15], ["standard", 18, 16], ["large", 20, 18]] as const) {
        await page.evaluate(value => { document.documentElement.dataset.readingTextSize = value; }, size);
        await expect(rows.first()).toHaveCSS("font-size", `${(narrow ? small : wide) * 0.75}px`);
        await expect.poll(async () => rows.first().evaluate(node => parseFloat(getComputedStyle(node).lineHeight)))
          .toBeCloseTo((narrow ? small : wide) * 0.75 * 1.6);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      const callbacks = page.getByRole("region", { name: "callbacks.tsx", exact: true });
      for (const [text, variable] of [["\"yes\"", "--code-string"], ["new", "--code-keyword"], ["save", "--code-function"], ["=>", "--code-function"], ["className", "--code-property"], ["span", "--code-property"]]) {
        await expectTokenColor(callbacks, text, variable);
      }
      const config = page.getByRole("region", { name: "config.ini", exact: true });
      await expect(config.locator("[data-code] [data-line]")).toHaveCount(4);
      await expectTokenColor(config, "; comment", "--code-comment");
      await expect(config.locator("[data-code] [data-line]").last()).toHaveText("host=localhost");
      const markdown = page.getByRole("region", { name: "table.md", exact: true });
      await expect(markdown.locator("[data-code] [data-line]")).toHaveCount(5);
      expect((await markdown.locator("[data-code] [data-line]").allTextContents()).map(line => line.replace(/\n$/, ""))).toEqual([
        "## 发布安排", "", "| 日期 | 角色 | 方向 |", "| --- | --- | --- |", "| 7/22 | trust / core | data-driven |",
      ]);
      await expect(page.getByRole("region", { name: "page.html", exact: true }).locator("[data-code] [data-line]"))
        .toHaveText('<script>alert("not executable")</script>');
      await expect(page.getByRole("region", { name: "bun.lock", exact: true }).locator("[data-code] [data-line]"))
        .toHaveText("unknown-language contents remain readable");
      const separated = page.getByRole("region", { name: "separated.ts", exact: true });
      await expect(separated.getByTestId("file-edit-diff-hunk-gap")).toHaveText(/21 unchanged lines hidden/);
      await expect(separated.locator("[data-code] [data-line]")).toHaveCount(8);
      await expect(separated.locator("[data-column-number]").last()).toContainText("27");
      await page.getByRole("button", { name: "Toggle theme" }).click();
      await expect(page.locator("html")).toHaveClass(dark ? "" : "dark");
      await expect(rows).toHaveCount(5);
      await expectKeywordColor(rows);
      for (const [text, variable] of [["\"yes\"", "--code-string"], ["new", "--code-keyword"], ["save", "--code-function"], ["=>", "--code-function"], ["className", "--code-property"], ["span", "--code-property"]]) {
        await expectTokenColor(callbacks, text, variable);
      }
      expect(errors).toEqual([]);
    });
  }
}

test("large diffs retain bounded expansion, release and truncated-file actions", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
  await page.goto("/browser/fixture.html?case=file-diff");
  const long = page.getByRole("region", { name: "long.ts", exact: true });
  const toggle = long.getByTestId("file-edit-diff-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(long.locator("diffs-container")).toHaveCount(0);
  await toggle.click();
  await expect(long.locator("[data-code] [data-line]")).toHaveCount(160);
  await expect(long.locator("[data-code] [data-line]").last()).toHaveText('export const item160 = "第 160 行 — readable code";');
  await long.getByTestId("file-edit-diff-expand-lines").click();
  const scroller = page.getByTestId("diff-fixture-scroller");
  const seen = new Set<number>();
  const height = await scroller.evaluate(node => node.scrollHeight);
  for (let top = 0; top <= height + 700; top += 700) {
    await scroller.evaluate((node, offset) => { node.scrollTop = offset; }, top);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const rows = await long.locator("[data-code] [data-line]").evaluateAll(nodes => nodes.map(node => ({ number: Number(node.getAttribute("data-line")), text: node.textContent?.replace(/\n$/, "") })));
    expect(rows.length).toBeLessThan(200);
    for (const row of rows) {
      expect(row.text).toBe(`export const item${row.number} = "第 ${row.number} 行 — readable code";`);
      seen.add(row.number);
    }
    expect(await scroller.evaluate(node => node.scrollHeight)).toBe(height);
  }
  expect([...seen].sort((a, b) => a - b)).toEqual(Array.from({ length: 600 }, (_, i) => i + 1));
  await expect(long.locator("[data-code] [data-line]").last()).toHaveText('export const item600 = "第 600 行 — readable code";');
  await long.getByTestId("file-edit-diff-collapse-lines").click();
  await expect(long.locator("[data-code] [data-line]")).toHaveCount(160);
  await toggle.click();
  await expect(long.getByTestId("file-edit-diff")).toHaveCount(0);
  await toggle.click();
  await expect(long.locator("[data-code] [data-line]")).toHaveCount(160);
  const truncated = page.getByRole("region", { name: "truncated.ts", exact: true });
  await truncated.getByTestId("file-edit-diff-toggle").click();
  await expect(truncated.getByTestId("file-edit-diff-truncated")).toContainText("Diff truncated");
  await truncated.getByTestId("file-edit-diff-open-file").click();
  await expect(page.getByRole("status", { name: "Opened file" })).toHaveText("/fixture/truncated.ts");
  expect(errors).toEqual([]);
});

for (const file of ["worker.ts", "long-separated.ts"]) {
  test(`windowed ${file} retains every source line and coordinate`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto("/browser/fixture.html?case=file-diff");
    const section = page.getByRole("region", { name: file, exact: true });
    await section.getByTestId("file-edit-diff-toggle").click();
    await expect(section.locator("[data-code] [data-line]")).toHaveCount(160);
    await expectKeywordColor(section.locator("[data-code] [data-line]"));
    await section.getByTestId("file-edit-diff-expand-lines").click();
    const scroller = page.getByTestId("diff-fixture-scroller");
    const seen = new Set<number>();
    const height = await scroller.evaluate(node => node.scrollHeight);
    for (let top = 0; top <= height + 700; top += 700) {
      await scroller.evaluate((node, offset) => { node.scrollTop = offset; }, top);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const rows = await section.locator("[data-code] [data-line]").evaluateAll(nodes => nodes.map(node => ({ number: Number(node.getAttribute("data-line")), text: node.textContent?.replace(/\n$/, ""), kind: node.getAttribute("data-line-type") })));
      expect(rows.length).toBeLessThan(200);
      for (const row of rows) {
        const index = file === "long-separated.ts" ? Math.floor((row.number - 1) / 500) * 200 + (row.number - 1) % 500 + 1 : row.number;
        expect(row.text).toBe(`export const item${index} = "第 ${index} 行 — readable code";${file === "worker.ts" ? ` // ${"worker source ".repeat(10)}` : ""}`);
        expect(row.kind).toBe("change-addition");
        seen.add(index);
      }
      expect(await scroller.evaluate(node => node.scrollHeight)).toBe(height);
    }
    expect([...seen].sort((a, b) => a - b)).toEqual(Array.from({ length: 600 }, (_, i) => i + 1));
    expect(errors).toEqual([]);
  });
}

test("a changed source replaces cached syntax without stale text", async ({ page }) => {
  await page.goto("/browser/fixture.html?case=file-diff");
  const section = page.getByRole("region", { name: "Status.tsx", exact: true });
  await expect(section.locator("[data-code] [data-line]").nth(3)).toHaveText('  return <span className="badge">ready</span>;');
  await page.getByRole("button", { name: "Change source" }).click();
  await expect(section.locator("[data-code] [data-line]").nth(3)).toHaveText('  return <span className="badge">updated</span>;');
  await expectKeywordColor(section.locator("[data-code] [data-line]"));
  const gap = page.getByRole("region", { name: "separated.ts", exact: true }).getByTestId("file-edit-diff-hunk-gap");
  await page.getByRole("button", { name: "Chinese", exact: true }).click();
  await expect(gap).toContainText("21");
  await expect(gap).toHaveText("…  已隐藏 21 行未修改内容");
});
