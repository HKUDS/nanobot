import { expect, test, type Locator } from "@playwright/test";

async function readMetrics(element: Locator) {
  return element.evaluate((node) => {
    if (!node.isConnected) return null;
    const style = getComputedStyle(node);
    return {
      size: parseFloat(style.fontSize), line: parseFloat(style.lineHeight), weight: style.fontWeight,
      family: style.fontFamily, letterSpacing: style.letterSpacing,
      padding: style.padding, autospace: style.getPropertyValue("text-autospace"),
    };
  });
}

async function metrics(element: Locator): Promise<NonNullable<Awaited<ReturnType<typeof readMetrics>>>> {
  let value: Awaited<ReturnType<typeof readMetrics>> = null;
  // Streamdown may replace a paragraph while settling its first render.
  await expect.poll(async () => {
    value = await readMetrics(element);
    return value !== null && Number.isFinite(value.size) && Number.isFinite(value.line);
  }).toBe(true);
  return value!;
}

for (const narrow of [false, true]) {
  for (const dark of [false, true]) {
    test(`reading hierarchy and stable controls: ${narrow ? "narrow" : "desktop"}, ${dark ? "dark" : "light"}`, async ({ page }, info) => {
      await page.setViewportSize(narrow ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
      await page.addInitScript((theme) => {
        localStorage.setItem("nanobot.locale", "zh-CN");
        localStorage.setItem("nanobot-webui.theme", theme);
      }, dark ? "dark" : "light");
      await page.goto("/browser/fixture.html?case=typography");
      const group = page.getByRole("radiogroup", { name: "阅读字号", exact: true });
      await expect(group.getByRole("radio", { name: "阅读字号：标准", exact: true })).toBeChecked();
      const heights = await group.evaluate((control) => {
        const row = control.closest(".settings-row")!;
        const nextRow = row.nextElementSibling!;
        return {
          readingRow: row.getBoundingClientRect().height,
          otherRow: nextRow.getBoundingClientRect().height,
          readingControl: control.getBoundingClientRect().height,
          otherControl: nextRow.querySelector(".segmented-control")!.getBoundingClientRect().height,
        };
      });
      expect(heights.readingRow).toBe(heights.otherRow);
      expect(heights.readingControl).toBe(heights.otherControl);
      const stable = await metrics(page.locator(".settings-row").first().locator(".text-control-label"));
      const observations = [];
      for (const [size, label, bodySize] of [
        ["small", "阅读字号：小", narrow ? 15 : 16],
        ["standard", "阅读字号：标准", narrow ? 16 : 18],
        ["large", "阅读字号：大", narrow ? 18 : 20],
      ] as const) {
        await group.getByRole("radio", { name: label, exact: true }).click();
        await expect(page.locator("html")).toHaveAttribute("data-reading-text-size", size);
        const paragraph = page.locator(".markdown-content p").first();
        await expect(paragraph).toHaveCSS("font-size", `${bodySize}px`);
        const body = await metrics(paragraph);
        expect(body.size).toBe(bodySize);
        expect(body.line).toBeCloseTo(bodySize * 1.8);
        expect(body.weight).toBe("400");
        expect((await metrics(page.locator("[data-user-text-bubble] p"))).size).toBe(bodySize);
        for (const selector of ["blockquote", "ol > li", ".task-list-item"]) {
          expect((await metrics(page.locator(`.markdown-content ${selector}`).first())).size).toBe(bodySize);
        }
        for (const [selector, ratio] of [["h1", 1.5], ["h2", 1.25], ["h3", 1.125], ["h4", 1]] as const) {
          const heading = await metrics(page.locator(`.markdown-content ${selector}`));
          expect(heading.size).toBeCloseTo(bodySize * ratio);
          expect(heading.weight).toBe("600");
        }
        for (const selector of ["table", "th", "td"]) {
          expect((await metrics(page.locator(`.markdown-content ${selector}`).first())).size).toBeCloseTo(bodySize * 0.875);
        }
        expect((await metrics(page.locator(".code-content pre"))).size).toBeCloseTo(bodySize * 0.875);
        expect((await metrics(page.locator(".markdown-inline-code"))).size).toBeCloseTo(bodySize * 0.875);
        expect((await metrics(page.locator("textarea"))).size).toBe(Math.max(16, bodySize));
        expect(await metrics(page.locator(".settings-row").first().locator(".text-control-label"))).toEqual(stable);
        const widths = await group.getByRole("radio").evaluateAll((nodes) => nodes.map(node => node.getBoundingClientRect().width));
        expect(Math.max(...widths) - Math.min(...widths)).toBeLessThan(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        observations.push({ size, body, widths });
        await page.locator(".markdown-content h1").evaluate(node => node.scrollIntoView({ block: "start" }));
        await page.screenshot({ path: info.outputPath(`${size}.png`) });
      }
      await info.attach("text-metrics", { body: JSON.stringify(observations, null, 2), contentType: "application/json" });
      await page.getByRole("button", { name: "复制代码", exact: true }).click();
      await expect(page.getByRole("button", { name: "已复制", exact: true })).toBeVisible();
      await page.locator("summary").click();
      await expect(page.getByText("这里的正文与折叠标题也应保持协调，不因字号变化发生裁切。")).toBeVisible();
    });
  }
}

test("keyboard, tooltip, persistence and unchanged preferences", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    if (!localStorage.getItem("nanobot-webui.settings-preferences")) {
      localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({
        schemaVersion: 1, codeWrap: false, brandLogos: false, activityMode: "expanded", notificationSound: true,
      }));
    }
  });
  await page.goto("/browser/fixture.html?case=typography");
  const standard = page.getByRole("radio", { name: "Standard reading text", exact: true });
  await standard.focus();
  await expect(page.getByRole("tooltip")).toHaveText("Standard reading text");
  expect(await standard.evaluate(node => node.matches(":focus-visible"))).toBe(true);
  await page.keyboard.press("ArrowRight");
  const large = page.getByRole("radio", { name: "Large reading text", exact: true });
  await expect(large).toBeFocused();
  await expect(large).toBeChecked();
  await expect(page.locator(".markdown-content p").first()).toHaveCSS("line-height", `${20 * 1.625}px`);
  await page.reload();
  await expect(page.getByRole("radio", { name: "Large reading text", exact: true })).toBeChecked();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("nanobot-webui.settings-preferences")!))).toMatchObject({
    readingTextSize: "large", codeWrap: false, brandLogos: false, activityMode: "expanded", notificationSound: true,
  });
});

test("touch composer keeps literal mention metrics and a safe editable minimum", async ({ browser, baseURL }, info) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  try {
    const page = await context.newPage();
    await page.addInitScript(() => localStorage.setItem("nanobot.locale", "en"));
    await page.goto("/browser/fixture.html?case=typography");
    const readingGroup = page.getByRole("radiogroup", { name: "Reading text size", exact: true });
    await expect(readingGroup.getByRole("radio")).toHaveCount(3);
    const heights = await readingGroup.evaluate((control) => {
      const row = control.closest(".settings-row")!;
      const nextRow = row.nextElementSibling!;
      return [row.getBoundingClientRect().height, nextRow.getBoundingClientRect().height];
    });
    expect(heights[0]).toBe(heights[1]);
    const radios = await readingGroup.getByRole("radio").all();
    for (const [index, radio] of radios.entries()) {
      await radio.scrollIntoViewIfNeeded();
      const target = await radio.boundingBox();
      expect(target!.width).toBeGreaterThanOrEqual(44);
      // The shared switch pattern extends the hit area without growing the pill.
      for (const edge of [-21, 21]) {
        await radios[(index + 1) % radios.length].tap();
        await page.touchscreen.tap(target!.x + target!.width / 2, target!.y + target!.height / 2 + edge);
        await expect(radio).toBeChecked();
      }
    }
    const input = page.getByRole("textbox", { name: "Message input", exact: true });
    await input.fill("中文 English @typography 混排\n多行内容与光标保持一致，继续输入 more text.\n最后一行。");
    for (const label of ["Small reading text", "Standard reading text", "Large reading text"]) {
      await page.getByRole("radio", { name: label, exact: true }).click();
      await input.focus();
      const overlay = page.locator(".thread-composer-input > div[aria-hidden]");
      await expect(overlay).toContainText("@typography");
      const text = await metrics(input);
      expect(text.size).toBeGreaterThanOrEqual(16);
      expect(await metrics(overlay)).toEqual(text);
      expect(text.autospace).toBe("no-autospace");
      expect(await input.evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBe(true);
      expect(await page.evaluate(() => visualViewport?.scale)).toBe(1);
    }
    await input.fill([...Array.from({ length: 18 }, (_, i) => `第 ${i + 1} 行 中文 English @typography 光标与装饰层。`), "最后一行。"].join("\n"));
    for (const label of ["Small reading text", "Standard reading text", "Large reading text"]) {
      await page.getByRole("radio", { name: label, exact: true }).click();
      await input.focus();
      await input.press("Control+End");
      const overlay = page.locator(".thread-composer-input > div[aria-hidden]");
      expect(await input.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
      await expect.poll(async () => Math.abs(await input.evaluate(node => node.scrollTop) - await overlay.evaluate(node => node.scrollTop))).toBeLessThanOrEqual(1);
      expect(await metrics(overlay)).toEqual(await metrics(input));
    }
    await page.keyboard.press("End");
    await page.keyboard.type("追加文字");
    await expect(input).toHaveValue(/最后一行。追加文字$/);
    await page.screenshot({ path: info.outputPath("touch-mention-caret.png") });
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect(page.locator("[data-user-text-bubble]").last()).toContainText("最后一行。追加文字");
  } finally {
    await context.close();
  }
});


test("large narrow reading keeps long lists and code reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    localStorage.setItem("nanobot.locale", "en");
    localStorage.setItem("nanobot-webui.settings-preferences", JSON.stringify({ schemaVersion: 1, readingTextSize: "large" }));
  });
  await page.goto("/browser/fixture.html?case=typography&stress");
  const lastItem = page.getByText("第 30 项：中文与 English 混排的长列表内容，保持自然换行和清楚的编号。", { exact: true });
  await lastItem.click();
  await expect(lastItem).toBeVisible();
  await expect(lastItem).toHaveCSS("font-size", "18px");
  const pre = page.locator(".code-content pre").last();
  await expect(pre).toContainText('const item79 = "第 80 行 — readable code";');
  await expect(pre).toHaveCSS("font-size", "15.75px");
  const finalLine = pre.getByText('"第 80 行 — readable code"', { exact: true });
  await finalLine.click();
  await expect(finalLine).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Copy code", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "Copied", exact: true })).toBeVisible();
  const input = page.getByRole("textbox", { name: "Message input", exact: true });
  await input.fill("读完长内容后仍然可以发送。Still usable.");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator("[data-user-text-bubble]").last()).toContainText("Still usable.");
});
